import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../baml_shared/baml_client')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from baml_client.types import AgentTask
from agent_fleet.langgraph_support.main import SupportRequest
from src.iagent.defs.dynamic_supervisor import SupervisorQueryConfig

def test_agent_task_user_id():
    """Test that AgentTask correctly accepts user_id"""
    task = AgentTask(
        task_description="Do something",
        dataset_id="123",
        user_id="test_user_456"
    )
    assert task.user_id == "test_user_456"
    assert task.task_description == "Do something"

    # Test optionality
    task2 = AgentTask(
        task_description="Do something else",
        dataset_id="789"
    )
    assert task2.user_id is None

def test_support_request_user_id():
    """Test that SupportRequest correctly accepts and defaults user_id"""
    req = SupportRequest(
        thread_id="thread_123",
        user_id="custom_user_id"
    )
    assert req.user_id == "custom_user_id"
    
    req2 = SupportRequest(
        thread_id="thread_456"
    )
    assert req2.user_id == "default_testing_user"

def test_supervisor_query_config_user_id():
    """Test that SupervisorQueryConfig correctly accepts and defaults user_id"""
    config = SupervisorQueryConfig(
        user_query="Hello",
        thread_id="thread_1",
        persona="MECHANIC",
        user_id="supervisor_user"
    )
    assert config.user_id == "supervisor_user"
    
    config2 = SupervisorQueryConfig(
        user_query="Hello",
        thread_id="thread_2",
        persona="MECHANIC"
    )
    assert config2.user_id == "default_testing_user"
