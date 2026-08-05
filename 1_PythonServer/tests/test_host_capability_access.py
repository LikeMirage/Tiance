from app.services.tools.host_capability_access import (
    HostCapability,
    HostCapabilityAccessService,
)


def test_only_approved_tool_can_receive_host_capability_grant():
    access = HostCapabilityAccessService()

    assert access.issue_grant(
        tool_name="read_text_file",
        tool_call_id="call-1",
        provider_id="provider-1",
        model_id="model-1",
        project_id="project-1",
        session_id="session-1",
        lifetime_seconds=60,
    ) is None


def test_grant_is_bound_to_current_tool_and_model_context():
    access = HostCapabilityAccessService()
    grant = access.issue_grant(
        tool_name="network_search",
        tool_call_id="call-1",
        provider_id="provider-1",
        model_id="model-1",
        project_id="project-1",
        session_id="session-1",
        lifetime_seconds=60,
    )

    assert grant is not None
    authorized = access.authorize(grant.token, HostCapability.WEB_SEARCH)
    assert authorized == grant
    assert authorized.provider_id == "provider-1"
    assert authorized.model_id == "model-1"
    assert authorized.project_id == "project-1"
    assert authorized.session_id == "session-1"

    access.revoke(grant.token)
    assert access.authorize(grant.token, HostCapability.WEB_SEARCH) is None


def test_grant_is_not_issued_without_complete_model_context():
    access = HostCapabilityAccessService()

    assert access.issue_grant(
        tool_name="network_search",
        tool_call_id="call-1",
        provider_id="provider-1",
        model_id=None,
        project_id=None,
        session_id=None,
        lifetime_seconds=60,
    ) is None


def test_manage_memory_receives_only_memory_capability():
    access = HostCapabilityAccessService()
    grant = access.issue_grant(
        tool_name="manage_memory",
        tool_call_id="call-memory",
        provider_id=None,
        model_id=None,
        project_id="project-1",
        session_id="session-1",
        lifetime_seconds=60,
    )

    assert grant is not None
    assert grant.capability is HostCapability.MEMORY_MANAGEMENT
    assert access.authorize(grant.token, HostCapability.MEMORY_MANAGEMENT) == grant
    assert access.authorize(grant.token, HostCapability.GITHUB_PLATFORM) is None
