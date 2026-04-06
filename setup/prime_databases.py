import os
import time
import argparse
import requests
import urllib3
from urllib.parse import urlparse
from neo4j import GraphDatabase

# Optional: weaviate is not strictly required if not wiping, but keeping for compatibility with old script
try:
    import weaviate
except ImportError:
    weaviate = None

proxy_int = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def parse_env():
    """Simple parser for local .env if python-dotenv is not installed"""
    env_vars = {}
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip("'").strip('"')
    
    for k, v in env_vars.items():
        if k not in os.environ:
            os.environ[k] = v

def get_base_url(url):
    """Safely extracts just the scheme and host:port from a full URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"

def prime_neo4j():
    print("--- Priming Neo4j (Constraints & Indexes) ---")
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    # Note: user/pw might need to be adjusted based on environment
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "changeme")
    
    cypher_commands = [
        "CREATE CONSTRAINT part_id_unique IF NOT EXISTS FOR (p:Part) REQUIRE p.id IS UNIQUE;",
        "CREATE CONSTRAINT proc_id_unique IF NOT EXISTS FOR (p:Procedure) REQUIRE p.id IS UNIQUE;",
        "CREATE CONSTRAINT step_id_unique IF NOT EXISTS FOR (s:ManufacturingStep) REQUIRE s.id IS UNIQUE;",
        "CREATE INDEX hazard_index IF NOT EXISTS FOR (h:Hazard) ON (h.class);"
    ]
    
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            for cmd in cypher_commands:
                session.run(cmd)
                print(f"  [OK] Executed: {cmd.split()[1]} {cmd.split()[2]}")
        driver.close()
        print("[SUCCESS] Neo4j successfully primed.")
    except Exception as e:
        print(f"  [ERROR] Failed to prime Neo4j: {e}")

def prime_jena():
    print("--- Priming Apache Jena (Auto-Provisioning) ---")
    
    # Configuration with safe base URL parsing
    raw_host = os.environ.get("JENA_URL")
    if not raw_host:
        # Fallback to JENA_SPARQL_ENDPOINT if JENA_URL is not set
        raw_host = os.environ.get("JENA_SPARQL_ENDPOINT", "http://localhost:3030")
    
    host = get_base_url(raw_host)
    ds_name = os.environ.get("JENA_DS", "ds")
    user = os.environ.get("JENA_USERNAME", "admin")
    pw = os.environ.get("FUSEKI_PASSWORD", "Admin123!") # matches docker-compose default
    auth = (user, pw)
    
    # 1. ENSURE DATASET EXISTS
    print(f"Checking for dataset /{ds_name} at {host}...")
    try:
        check = requests.get(f"{host}/$/datasets/{ds_name}", auth=auth, proxies=proxy_int, verify=False)
        if check.status_code == 404:
            print(f"  [!] Dataset /{ds_name} not found. Creating it now...")
            # Create a persistent TDB2 dataset
            create_params = {'dbName': ds_name, 'dbType': 'tdb2'}
            create_res = requests.post(f"{host}/$/datasets", data=create_params, auth=auth, proxies=proxy_int, verify=False)
            if create_res.status_code in [200, 201]:
                print(f"  [SUCCESS] Dataset /{ds_name} created.")
            else:
                print(f"  [ERROR] Could not create dataset: {create_res.status_code} {create_res.text}")
                return
        else:
            print(f"  [OK] Dataset /{ds_name} exists.")
    except Exception as e:
        print(f"  [ERROR] Connection failed: {e}")
        return

    # 2. LOAD ONTOLOGIES
    ontologies = [
        # LAYER 1: MAINTENANCE
        {"domain": "mro", "name": "IOF_Core", "path": "https://raw.githubusercontent.com/iofoundry/ontology/master/core/Core.rdf"},
        {"domain": "mro", "name": "DINEN62264", "path": "https://raw.githubusercontent.com/hsu-aut/IndustrialStandard-ODP-DINEN62264-2/v1.4.2/DINEN62264.owl"}, 
        {"domain": "mro", "name": "IOF_MRO", "path": "https://raw.githubusercontent.com/iofoundry/ontology/master/maintenance/Maintenance.rdf"}, 
        {"domain": "mro", "name": "MIL_Unified", "path": "https://raw.githubusercontent.com/edgy-solutions/doc-tools/main/setup/mil_ontology.ttl"},
        {"domain": "mro", "name": "Munitions", "path": "https://raw.githubusercontent.com/edgy-solutions/doc-tools/main/setup/munitions_ontology.ttl"},
        
        # LAYER 2: SUSTAINMENT
        {"domain": "sustainment", "name": "IOF_Core", "path": "https://raw.githubusercontent.com/iofoundry/ontology/master/core/Core.rdf"},
        {"domain": "sustainment", "name": "S3000L", "path": "https://www.semanticstep.org/sites/default/files/2018-01/s3kl_0.ttl"}, 
        
        # LAYER 3: DATA ENGINEERING (IDP)
        {"domain": "idp", "name": "PROV-O", "path": "https://www.w3.org/ns/prov-o.ttl"}, 
    ]

    domain_mapping = {
        "mro": "http://internal/mro",
        "sustainment": "http://internal/sustainment",
        "idp": "http://internal/idp"
    }

    for ont in ontologies:
        domain = ont.get("domain", "default")
        graph_uri = domain_mapping.get(domain, "default")
        print(f"Loading {ont['name']} into graph <{graph_uri}>...")
        
        try:
            if ont["path"].startswith("http"):
                resp = requests.get(ont["path"], verify=False, timeout=15)
                resp.raise_for_status()
                data = resp.content
            else:
                if not os.path.exists(ont["path"]):
                    print(f"  [WARNING] File not found: {ont['path']}. Skipping.")
                    continue
                with open(ont["path"], "rb") as f:
                    data = f.read()
            
            # Content Type Logic
            c_type = "application/rdf+xml" if ont["path"].endswith((".rdf", ".owl")) else "text/turtle"
            
            # Upload using Graph Store Protocol
            # ?graph=... for named graphs
            res = requests.post(
                f"{host}/{ds_name}/data?graph={graph_uri}",
                data=data,
                headers={"Content-Type": f"{c_type}; charset=utf-8"},
                auth=auth,
                verify=False
            )
            
            if res.status_code in [200, 201, 204]:
                print(f"  [SUCCESS] Loaded {ont['name']}.")
            else:
                print(f"  [FAILED] {ont['name']} Status: {res.status_code} {res.text}")
        except Exception as e:
            print(f"  [ERROR] {ont['name']}: {e}")

def wipe_databases(wipe_neo4j_weaviate=True, wipe_jena=False):
    print("=== DANGER: Wiping Databases ===")
    
    if wipe_neo4j_weaviate:
        # 1. Neo4j Wipe
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USERNAME", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "changeme")
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            with driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
            driver.close()
            print("[SUCCESS] Neo4j graph cleared.")
        except Exception as e:
            print(f"[ERROR] Failed to clear Neo4j: {e}")

        # 2. Weaviate Wipe
        if weaviate:
            weaviate_url = os.environ.get("WEAVIATE_URL", "http://localhost:8080")
            try:
                client = weaviate.Client(weaviate_url)
                client.schema.delete_all()
                print("[SUCCESS] Weaviate schemas and vectors cleared.")
            except Exception as e:
                print(f"[ERROR] Failed to clear Weaviate: {e}")
        else:
            print("[INFO] weaviate-client not installed, skipping Weaviate wipe.")

    if wipe_jena:
        # 3. Jena Wipe 
        raw_host = os.environ.get("JENA_URL", "http://localhost:3030")
        host = get_base_url(raw_host)
        ds_name = os.environ.get("JENA_DS", "ds")
        user = os.environ.get("JENA_USERNAME", "admin")
        pw = os.environ.get("FUSEKI_PASSWORD", "Admin123!")
        
        try:
            update_query = "CLEAR ALL"
            res = requests.post(
                f"{host}/{ds_name}/update",
                data={"update": update_query},
                auth=(user, pw),
                verify=False
            )
            
            if res.status_code in [200, 204]:
                print(f"[SUCCESS] Jena dataset /{ds_name} contents cleared.")
            else:
                print(f"[ERROR] Failed to clear Jena contents: {res.status_code} {res.text}")
        except Exception as e:
            print(f"[ERROR] Failed to connect to Jena to clear data: {e}")

def main():
    parser = argparse.ArgumentParser(description="Document Tools Environment Setup")
    parser.add_argument("--wipe", action="store_true", help="Clear data from Neo4j and Weaviate.")
    parser.add_argument("--wipe-jena", action="store_true", help="Clear semantic ontology data from Apache Jena.")
    args = parser.parse_args()

    parse_env()
    
    if args.wipe or args.wipe_jena:
        wipe_databases(wipe_neo4j_weaviate=args.wipe, wipe_jena=args.wipe_jena)
        if not (args.wipe or args.wipe_jena): # if only wiping, don't prime unless requested? 
            # Usually we don't return here if we want to prime after wipe, but the old script returns.
            return

    print("=== Starting Virgin Environment Pre-Flight Checklist ===")
    time.sleep(1)
    
    prime_neo4j()
    prime_jena()

if __name__ == "__main__":
    main()
