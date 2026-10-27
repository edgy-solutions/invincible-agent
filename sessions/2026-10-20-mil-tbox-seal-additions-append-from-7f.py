"""Does live + additions equal the verified merge, triple for triple?

The deliverable is a file 74 APPENDS to setup/ontologies/mil_extension.ttl.
So the thing to seal is not the merge I hand over for reading -- it is that
appending the additions to the live carrier reproduces that merge exactly.
argv: <live mil_extension.ttl> <additions> <merged>
"""
import sys
from rdflib import Graph, URIRef

MIL = "http://edgy-solutions.com/ontology/mil#"

live = Graph(); live.parse(sys.argv[1], format="turtle")
add = Graph(); add.parse(sys.argv[2], format="turtle")
merged = Graph(); merged.parse(sys.argv[3], format="turtle")

appended = set(live) | set(add)
mt = set(merged)
print("live triples:", len(live), " additions:", len(add),
      " appended union:", len(appended), " merged file:", len(mt))
print("in merged, NOT in appended:", len(mt - appended))
for t in sorted(mt - appended, key=str)[:10]:
    print("   ", t)
print("in appended, NOT in merged:", len(appended - mt))
for t in sorted(appended - mt, key=str)[:10]:
    print("   ", t)

subs = {str(s)[len(MIL):] for s in set(merged.subjects())
        if isinstance(s, URIRef) and str(s).startswith(MIL)}
print("mil subjects after append:", len(subs))

bad = []
for t in sorted(subs):
    u = URIRef(MIL + t)
    d = list(merged.objects(u, URIRef("http://www.w3.org/2004/02/skos/core#definition")))
    c = list(merged.objects(u, URIRef("http://www.w3.org/2000/01/rdf-schema#comment")))
    if len(d) != 1 or c:
        bad.append((t, len(d), len(c)))
print("terms with other than exactly one definition and zero comment:", bad or "none")
print("VERDICT:", "APPEND REPRODUCES THE MERGE" if appended == mt else "MISMATCH")
