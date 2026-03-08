"""Typed entity schemas and relationship constraints for the ontology extraction pipeline.

This file is the SINGLE SOURCE OF TRUTH for:
1. What entity types exist and what typed attributes each has
2. What relationship types exist and what source/target type constraints they have
3. Auto-generation of extraction prompt sections from these definitions
4. Validation of extracted entities and relationships against schemas

User provides the actual schema content (typed attributes on subclasses,
relationship registry entries). This module provides the FRAMEWORK.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal, Optional, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, ValidationError

from src.base_models import SourceAnchor

log = logging.getLogger(__name__)


# ============================================================
# BASE ENTITY SCHEMA
# ============================================================


class BaseEntitySchema(BaseModel):
    """Base class for all typed entity schemas.

    Every entity subclass MUST:
    1. Override `type` with a Literal for its specific type string
    2. Define typed attribute fields with Field(description=...)
    3. Give all typed attribute fields defaults (empty string, None, etc.)

    extra="allow" captures unexpected LLM attributes in __pydantic_extra__
    rather than raising validation errors. Phase 2 replaces this with the
    full 4-tier unknown-attribute protocol.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    type: str  # Overridden as Literal["..."] in each subclass
    name: str
    description: str
    source_anchor: SourceAnchor = Field(default_factory=SourceAnchor)
    source_anchors: list[SourceAnchor] = []
    appears_in: list[str] = Field(
        default=[],
        description="Section IDs (SEC-XX) where this entity was extracted.",
    )


# ============================================================
# TYPED ENTITY SCHEMAS — Duty of Care & Travel Risk Management
# Stubs — user fills in typed attribute fields on each subclass.
# All typed fields MUST have defaults so partial extraction doesn't fail.
# Use Field(description="...") on every attribute for prompt generation.
# ============================================================


class OrganizationEntity(BaseEntitySchema):
    """Any corporate or institutional entity that is a party to, or
    referenced within, the agreement ecosystem. Includes TMCs, clients,
    specialist providers, travel suppliers, and regulatory bodies."""

    type: Literal["Organization"] = "Organization"


class AgreementEntity(BaseEntitySchema):
    """A contractual or regulatory document that establishes terms,
    obligations, or scope — such as a Travel Services Agreement,
    Exhibit D (Duty of Care), Statement of Work, or Data Processing
    Agreement."""

    type: Literal["Agreement"] = "Agreement"


class TravelerEntity(BaseEntitySchema):
    """An individual authorized by Client who travels on Client business
    and whose itinerary may be managed under the duty of care program.
    Includes employees, contractors, consultants, board members,
    candidates, and guests."""

    type: Literal["Traveler"] = "Traveler"


class IncidentEntity(BaseEntitySchema):
    """A discrete event that may reasonably impact traveler safety,
    security, health, or ability to continue travel — such as a
    terrorist attack, natural disaster, airline grounding, or disease
    outbreak."""

    type: Literal["Incident"] = "Incident"


class SeverityLevelEntity(BaseEntitySchema):
    """A tiered classification (Level 1-4) that determines the urgency
    of response, service level objectives, and escalation requirements.
    SLO targets are embedded as properties to enable direct query of
    time-bound obligations without requiring a separate entity."""

    type: Literal["SeverityLevel"] = "SeverityLevel"

    level: Optional[int] = Field(
        default=None,
        description="Severity tier: 1, 2, 3, or 4.",
    )
    classification: str = Field(
        default="",
        description=(
            "Advisory | Monitor | ActionRequired | Crisis"
        ),
    )
    alert_time_target: str = Field(
        default="",
        description=(
            "SLO for traveler alert/outreach initiation "
            "(e.g., 'within 30 minutes' for Level 4)."
        ),
    )
    client_escalation_time_target: str = Field(
        default="",
        description=(
            "SLO for client escalation notification "
            "(e.g., 'within 60 minutes' for Level 3)."
        ),
    )
    status_update_cadence: str = Field(
        default="",
        description=(
            "Required frequency of status updates while incident is active "
            "(e.g., 'every 30 min acute / hourly sustained' for Level 4)."
        ),
    )
    crisis_bridge_required: Optional[bool] = Field(
        default=None,
        description=(
            "Whether a Crisis Bridge must be established (true only for Level 4)."
        ),
    )


class ServiceEntity(BaseEntitySchema):
    """A defined component of the duty of care program that the TMC
    provides to Client and its travelers — such as Itinerary Visibility,
    Risk Intelligence, Pre-Trip Services, In-Trip Monitoring, Incident
    Response, or Post-Incident Reporting."""

    type: Literal["Service"] = "Service"

    activation_severity_threshold: Optional[int] = Field(
        default=None,
        description=(
            "Minimum severity level at which this service activates "
            "(e.g., 2 for Incident Response, 4 for Crisis Bridge). "
            "None if always active."
        ),
    )
    requires_client_authorization: Optional[bool] = Field(
        default=None,
        description=(
            "Whether this service requires express Client authorization "
            "before the TMC may proceed."
        ),
    )
    authorization_details: str = Field(
        default="",
        description=(
            "Specific actions within this service that require authorization "
            "and any SOW exceptions."
        ),
    )


class RegulationEntity(BaseEntitySchema):
    """A law, directive, standard, or regulatory framework that governs
    or informs duty of care obligations and data handling — such as
    OSHA, UK HSWA 1974, EU Directive 89/391/EEC, ISO 31030:2021,
    or GDPR."""

    type: Literal["Regulation"] = "Regulation"


class PlatformEntity(BaseEntitySchema):
    """A technology system or tool used to deliver, support, or enable
    duty of care services — such as a risk intelligence platform, OBT,
    GDS, mobile application, or reporting dashboard."""

    type: Literal["Platform"] = "Platform"


class BookingChannelEntity(BaseEntitySchema):
    """A method or pathway through which travel is booked, determining
    whether the booking is visible to the TMC and whether duty of care
    services can be rendered. Includes approved channels (OBT, agent-
    assisted) and off-channel bookings (consumer sites, direct supplier)."""

    type: Literal["BookingChannel"] = "BookingChannel"


class RiskCategoryEntity(BaseEntitySchema):
    """A classification of threat or hazard type that the risk
    intelligence monitoring program covers — such as Security, Natural
    Hazard, Health, Transportation, Political/Regulatory, or
    Infrastructure."""

    type: Literal["RiskCategory"] = "RiskCategory"


class ContactRoleEntity(BaseEntitySchema):
    """A named position on Client's 24/7 escalation roster to which
    incidents and non-responsive traveler cases are escalated — such as
    Primary Travel Program Owner, Corporate Security, HR Duty Contact,
    or Senior Leadership Contact."""

    type: Literal["ContactRole"] = "ContactRole"

    escalation_severity_levels: list[int] = Field(
        default=[],
        description=(
            "Severity levels at which this contact role is engaged "
            "(e.g., [3, 4] for Corporate Security)."
        ),
    )
    escalation_condition: str = Field(
        default="",
        description=(
            "Additional condition beyond severity level that triggers "
            "engagement (e.g., 'security-related incidents', 'outside "
            "Business Hours', 'employee welfare, injury, or fatality')."
        ),
    )
    roster_position: str = Field(
        default="",
        description=(
            "Role in escalation sequence: Primary | Backup | Conditional | CrisisOnly"
        ),
    )


class DataElementEntity(BaseEntitySchema):
    """A specific field of traveler profile data required for effective
    duty of care service delivery — such as full legal name, mobile
    phone number, email address, emergency contact, passport details,
    or nationality."""

    type: Literal["DataElement"] = "DataElement"


class TravelerResponseStatusEntity(BaseEntitySchema):
    """A standardized welfare-check response classification that
    determines subsequent TMC action — SAFE, NEED ASSISTANCE, NOT IN
    AREA, or No Response."""

    type: Literal["TravelerResponseStatus"] = "TravelerResponseStatus"

    tmc_action: str = Field(
        default="",
        description=(
            "The specific follow-up action the TMC must take when a traveler "
            "returns this status (e.g., 'Attempt live contact within 15 minutes; "
            "provide assistance per Section 3.5')."
        ),
    )
    action_time_target: str = Field(
        default="",
        description=(
            "Time constraint on the TMC's follow-up action, if any "
            "(e.g., '15 minutes' for NEED ASSISTANCE live contact)."
        ),
    )
    closes_outreach: Optional[bool] = Field(
        default=None,
        description=(
            "Whether this response removes the traveler from active outreach "
            "for this incident (True for SAFE and NOT IN AREA)."
        ),
    )
    triggers_escalation: Optional[bool] = Field(
        default=None,
        description=(
            "Whether this status triggers escalation to Client contacts "
            "(True for NO RESPONSE after outreach window)."
        ),
    )


class ObligationEntity(BaseEntitySchema):
    """A specific contractual duty or requirement assigned to a party
    under the agreement, representing an actionable responsibility that
    the TMC or Client must fulfill."""

    type: Literal["Obligation"] = "Obligation"

    section_reference: str = Field(
        default="",
        description="Document section(s) where the obligation is defined.",
    )
    obligation_type: str = Field(
        default="",
        description=(
            "Operational | Data | Policy | Financial | Authorization"
        ),
    )
    obligated_party: str = Field(
        default="",
        description="TMC | Client",
    )
    conditionality: str = Field(
        default="",
        description=(
            "Trigger or condition under which the obligation applies "
            "(e.g., 'during Level 3-4 Incidents', 'for international travel')."
        ),
    )


class AlertEntity(BaseEntitySchema):
    """An outbound communication sent to a Traveler or ContactRole in
    connection with an Incident, including advisories, welfare checks,
    escalation notifications, and SITREPs."""

    type: Literal["Alert"] = "Alert"

    alert_type: str = Field(
        default="",
        description="Advisory | WelfareCheck | EscalationNotification | SITREP",
    )
    severity_level: Optional[int] = Field(
        default=None,
        description=(
            "The severity level this alert template corresponds to (1-4), "
            "enabling direct lookup of which alert type applies at which severity."
        ),
    )
    channel: str = Field(
        default="",
        description="SMS | Email | VoiceCall | MobileAppPush",
    )
    channel_priority_order: Optional[int] = Field(
        default=None,
        description=(
            "Priority rank of this channel in the outreach sequence "
            "(1=highest priority, attempted first). Default order: "
            "1=SMS, 2=Email, 3=MobileAppPush, 4=VoiceCall."
        ),
    )
    attempt_number: Optional[int] = Field(
        default=None,
        description="Sequential attempt number for welfare-check retries.",
    )
    content: str = Field(
        default="",
        description="Message body or template reference (Appendix B).",
    )
    outcome: str = Field(
        default="",
        description="Delivered | Failed | NoResponse | ResponseReceived",
    )


class BookingEntity(BaseEntitySchema):
    """A travel reservation record (PNR) containing itinerary segments
    that provides the TMC with visibility into a Traveler's planned
    location — the foundational data object upon which all duty of care
    services depend."""

    type: Literal["Booking"] = "Booking"

    pnr_id: str = Field(
        default="",
        description="GDS or NDC record locator.",
    )
    segments: list[str] = Field(
        default=[],
        description="Segment types included (air, hotel, rail, car, ground).",
    )
    status: str = Field(
        default="",
        description="Active | Modified | Cancelled",
    )
    destinations: list[str] = Field(
        default=[],
        description="Cities/countries in the itinerary.",
    )
    capture_method: str = Field(
        default="",
        description=(
            "DirectBooking | EmailParsing | SupplierFeed | ExpenseIntegration"
        ),
    )


class WorkflowEntity(BaseEntitySchema):
    """A named multi-step procedure defined in the policy — such as
    the welfare check outreach sequence, the escalation procedure,
    or the Crisis Bridge establishment protocol."""

    type: Literal["Workflow"] = "Workflow"

    trigger_condition: str = Field(
        default="",
        description=(
            "Condition that initiates this workflow "
            "(e.g., 'Incident classified at Level 3 or higher')."
        ),
    )
    step_count: Optional[int] = Field(
        default=None,
        description="Number of sequential steps in this workflow.",
    )
    time_constraint: str = Field(
        default="",
        description=(
            "Overall time constraint or SLO for the workflow "
            "(e.g., 'Crisis Bridge established within 60 minutes')."
        ),
    )


# ============================================================
# ENTITY TYPE REGISTRY (auto-derived from BaseEntitySchema subclasses)
# ============================================================


def _discover_entity_classes() -> list[type[BaseEntitySchema]]:
    """Find all concrete BaseEntitySchema subclasses defined in this module.

    A subclass is concrete if its `type` field has a Literal default
    (i.e., it overrides the base `type: str` with `type: Literal["..."]`).
    """
    import sys

    module = sys.modules[__name__]
    classes: list[type[BaseEntitySchema]] = []
    for name in dir(module):
        obj = getattr(module, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseEntitySchema)
            and obj is not BaseEntitySchema
            and "type" in obj.model_fields
            and obj.model_fields["type"].default is not None
        ):
            classes.append(obj)
    # Sort by type name for deterministic ordering
    classes.sort(key=lambda c: c.model_fields["type"].default)
    return classes


ENTITY_TYPE_CLASSES: list[type[BaseEntitySchema]] = _discover_entity_classes()

ENTITY_TYPE_MAP: dict[str, type[BaseEntitySchema]] = {
    cls.model_fields["type"].default: cls for cls in ENTITY_TYPE_CLASSES
}

VALID_ENTITY_TYPES: set[str] = set(ENTITY_TYPE_MAP.keys())

# Forbidden type aliases: maps invalid type names to the correct type.
# Used in prompt generation to tell the LLM what NOT to use.
FORBIDDEN_TYPE_ALIASES: dict[str, str] = {}


# ============================================================
# DISCRIMINATED UNION (auto-built from discovered entity classes)
# ============================================================


def _entity_discriminator(v: Any) -> str:
    """Route entity dicts to the correct typed subclass by the 'type' field."""
    t = v.get("type", "") if isinstance(v, dict) else getattr(v, "type", "")
    if t not in VALID_ENTITY_TYPES:
        raise ValueError(
            f"Unknown entity type: '{t}'. "
            f"Valid types: {sorted(VALID_ENTITY_TYPES)}"
        )
    return t


def _build_any_entity_type():
    """Build the AnyEntity discriminated union from all discovered subclasses."""
    members = tuple(
        Annotated[cls, Tag(cls.model_fields["type"].default)]
        for cls in ENTITY_TYPE_CLASSES
    )
    return Annotated[Union[members], Discriminator(_entity_discriminator)]  # type: ignore[valid-type]


AnyEntity = _build_any_entity_type()


# ============================================================
# RELATIONSHIP SCHEMA REGISTRY
# ============================================================


class RelationshipSchema(BaseModel):
    """Schema defining a valid relationship type and its constraints."""

    type: str
    description: str
    valid_source_types: list[str] = []  # Empty = any type allowed
    valid_target_types: list[str] = []  # Empty = any type allowed
    cardinality: str = "many_to_many"
    is_directed: bool = True
    mandatory: bool = False
    inverse_type: str | None = None
    agent_traversal_hint: str = ""


# ============================================================
# RELATIONSHIP SCHEMAS — Duty of Care & Travel Risk Management
# ============================================================

PARTY_TO = RelationshipSchema(
    type="PARTY_TO",
    description=(
        "An organization is a signatory, party, or subject of a contractual document."
    ),
    valid_source_types=["Organization"],
    valid_target_types=["Agreement"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse to identify which organizations are bound by which agreements. "
        "Start from Organization to find its contractual commitments, or from "
        "Agreement to find all parties."
    ),
)

INCORPORATES = RelationshipSchema(
    type="INCORPORATES",
    description=(
        "One contractual document is incorporated into, references, or takes "
        "precedence over another."
    ),
    valid_source_types=["Agreement"],
    valid_target_types=["Agreement"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse to understand the hierarchy of contractual documents and which "
        "agreement governs when terms conflict."
    ),
)

PROVIDES = RelationshipSchema(
    type="PROVIDES",
    description=(
        "An organization delivers or performs a duty of care service."
    ),
    valid_source_types=["Organization"],
    valid_target_types=["Service"],
    cardinality="one_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Organization to find what services it delivers, or from "
        "Service to identify the responsible provider."
    ),
)

ENGAGES = RelationshipSchema(
    type="ENGAGES",
    description=(
        "One organization contracts, subcontracts, or designates another for "
        "specialized capabilities."
    ),
    valid_source_types=["Organization"],
    valid_target_types=["Organization"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse to map the subcontracting and specialist provider network."
    ),
)

OPERATES = RelationshipSchema(
    type="OPERATES",
    description=(
        "An organization manages, hosts, or provides a technology platform."
    ),
    valid_source_types=["Organization"],
    valid_target_types=["Platform"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse to find which organization is responsible for a given platform, "
        "or what platforms an organization operates."
    ),
)

CLASSIFIED_AS = RelationshipSchema(
    type="CLASSIFIED_AS",
    description=(
        "An incident is assessed and assigned a severity tier that governs "
        "response obligations."
    ),
    valid_source_types=["Incident"],
    valid_target_types=["SeverityLevel"],
    cardinality="many_to_one",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Incident to determine its severity classification and "
        "the associated SLO targets, escalation requirements, and response cadence."
    ),
)

CATEGORIZED_AS = RelationshipSchema(
    type="CATEGORIZED_AS",
    description=(
        "An incident is typed under one or more risk intelligence categories."
    ),
    valid_source_types=["Incident"],
    valid_target_types=["RiskCategory"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Incident to identify its risk category for monitoring "
        "and intelligence purposes."
    ),
)

IMPACTS = RelationshipSchema(
    type="IMPACTS",
    description=(
        "An incident potentially affects one or more travelers who are in or "
        "near the impact zone based on itinerary data."
    ),
    valid_source_types=["Incident"],
    valid_target_types=["Traveler"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Incident to identify all potentially affected travelers, "
        "or from Traveler to find incidents impacting them."
    ),
)

RESPONDS_WITH = RelationshipSchema(
    type="RESPONDS_WITH",
    description=(
        "A traveler replies to a welfare-check outreach with a standardized status."
    ),
    valid_source_types=["Traveler"],
    valid_target_types=["TravelerResponseStatus"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Traveler to determine their welfare-check response status "
        "and trigger the appropriate follow-up action."
    ),
)

ACTIVATED_AT = RelationshipSchema(
    type="ACTIVATED_AT",
    description=(
        "A duty of care service component is triggered or required at a specific "
        "severity threshold."
    ),
    valid_source_types=["Service"],
    valid_target_types=["SeverityLevel"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Service to find the severity levels at which it activates, "
        "or from SeverityLevel to enumerate all services triggered at that tier."
    ),
)

ENABLED_BY = RelationshipSchema(
    type="ENABLED_BY",
    description=(
        "A service depends on a technology platform for delivery or execution."
    ),
    valid_source_types=["Service"],
    valid_target_types=["Platform"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Service to identify its technology dependencies, or from "
        "Platform to find all services it enables."
    ),
)

COMPLIES_WITH = RelationshipSchema(
    type="COMPLIES_WITH",
    description=(
        "A contractual document or the services it governs are designed to "
        "satisfy or align with a regulatory framework."
    ),
    valid_source_types=["Agreement"],
    valid_target_types=["Regulation"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Agreement to find all regulatory frameworks it satisfies, "
        "or from Regulation to find agreements that comply with it."
    ),
)

DESIGNATED_BY = RelationshipSchema(
    type="DESIGNATED_BY",
    description=(
        "An escalation roster role is staffed and maintained by an organization."
    ),
    valid_source_types=["ContactRole"],
    valid_target_types=["Organization"],
    cardinality="many_to_one",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from ContactRole to find the responsible organization, or from "
        "Organization to enumerate its designated escalation contacts."
    ),
)

REQUIRES_DATA = RelationshipSchema(
    type="REQUIRES_DATA",
    description=(
        "A service depends on specific traveler profile data to function effectively."
    ),
    valid_source_types=["Service"],
    valid_target_types=["DataElement"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Service to find its data dependencies, or from DataElement "
        "to find all services that depend on it."
    ),
)

TRIGGERS_ACTION = RelationshipSchema(
    type="TRIGGERS_ACTION",
    description=(
        "A specific welfare-check response status initiates a defined TMC "
        "follow-up action."
    ),
    valid_source_types=["TravelerResponseStatus"],
    valid_target_types=["Service"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from TravelerResponseStatus to determine what follow-up "
        "services or actions are triggered by each response classification."
    ),
)

ESCALATED_TO = RelationshipSchema(
    type="ESCALATED_TO",
    description=(
        "A severity level requires notification to specific escalation roster "
        "roles, defining the policy-driven escalation path."
    ),
    valid_source_types=["SeverityLevel"],
    valid_target_types=["ContactRole"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from SeverityLevel to determine which escalation roster roles "
        "must be notified at each tier, including time targets for notification."
    ),
)

HAS_BOOKING = RelationshipSchema(
    type="HAS_BOOKING",
    description=(
        "A traveler has a travel reservation record that provides the TMC "
        "with itinerary visibility."
    ),
    valid_source_types=["Traveler"],
    valid_target_types=["Booking"],
    cardinality="one_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Traveler to find their active bookings and itinerary "
        "segments for traveler locate and duty of care purposes."
    ),
)

BOOKED_THROUGH = RelationshipSchema(
    type="BOOKED_THROUGH",
    description=(
        "A booking was made through a specific channel, determining whether "
        "the reservation is visible to the TMC for duty of care purposes."
    ),
    valid_source_types=["Booking"],
    valid_target_types=["BookingChannel"],
    cardinality="many_to_one",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Booking to determine its channel and whether the TMC "
        "has visibility. Enables queries like 'show all bookings with no TMC visibility'."
    ),
)

ENABLES_COVERAGE = RelationshipSchema(
    type="ENABLES_COVERAGE",
    description=(
        "An approved booking channel provides the itinerary visibility required "
        "for duty of care services to function; off-channel bookings represent "
        "a material coverage gap."
    ),
    valid_source_types=["BookingChannel"],
    valid_target_types=["Service"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from BookingChannel to determine which duty of care services "
        "are enabled or blocked by the channel choice."
    ),
)

REQUIRES_AUTHORIZATION_FROM = RelationshipSchema(
    type="REQUIRES_AUTHORIZATION_FROM",
    description=(
        "Specific service actions require express authorization from a "
        "designated party before the TMC may proceed."
    ),
    valid_source_types=["Service"],
    valid_target_types=["Organization"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Service to find which organization must authorize "
        "extraordinary measures before the TMC may proceed."
    ),
)

ASSIGNED_TO = RelationshipSchema(
    type="ASSIGNED_TO",
    description=(
        "A contractual obligation is borne by a specific party (TMC or Client)."
    ),
    valid_source_types=["Obligation"],
    valid_target_types=["Organization"],
    cardinality="many_to_one",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Obligation to find the responsible party, or from "
        "Organization to enumerate all obligations assigned to it."
    ),
)

RELATES_TO = RelationshipSchema(
    type="RELATES_TO",
    description=(
        "An obligation pertains to, enables, or constrains a specific duty "
        "of care service."
    ),
    valid_source_types=["Obligation"],
    valid_target_types=["Service"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Obligation to find the services it supports or constrains, "
        "or from Service to find all obligations that relate to it."
    ),
)

DEFINED_IN = RelationshipSchema(
    type="DEFINED_IN",
    description=(
        "An obligation is established or specified within a particular "
        "contractual document."
    ),
    valid_source_types=["Obligation"],
    valid_target_types=["Agreement"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Obligation to its contractual source, or from Agreement "
        "to enumerate all obligations defined within it."
    ),
)

TRIGGERED_BY = RelationshipSchema(
    type="TRIGGERED_BY",
    description=(
        "An alert or outreach communication is initiated in response to a "
        "specific incident."
    ),
    valid_source_types=["Alert"],
    valid_target_types=["Incident"],
    cardinality="many_to_one",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Alert to find its causal incident, or from Incident "
        "to enumerate all alerts it triggered."
    ),
)

SENT_TO = RelationshipSchema(
    type="SENT_TO",
    description=(
        "An alert or welfare-check outreach is delivered to a specific "
        "traveler via a configured channel."
    ),
    valid_source_types=["Alert"],
    valid_target_types=["Traveler"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from Alert to find all travelers it was sent to, or from "
        "Traveler to find all alerts received. Enables tracking of outreach "
        "attempts, channels, and outcomes per Appendix C."
    ),
)

FOLLOWED_BY = RelationshipSchema(
    type="FOLLOWED_BY",
    description=(
        "One step in a procedure is followed by another step in sequence. "
        "Used to model ordered workflows such as the welfare check outreach "
        "sequence (SMS → Email → Push → Voice) or escalation chains."
    ),
    valid_source_types=[
        "Service", "Alert", "TravelerResponseStatus", "Obligation", "Workflow",
    ],
    valid_target_types=[
        "Service", "Alert", "TravelerResponseStatus", "Obligation", "Workflow",
    ],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse to determine the ordered sequence of steps in a procedure. "
        "Follow the FOLLOWED_BY chain from the first step to enumerate the "
        "complete workflow in order."
    ),
)

CONDITIONAL_ON = RelationshipSchema(
    type="CONDITIONAL_ON",
    description=(
        "An action, service, or escalation is conditional on a specific "
        "criterion being met — such as a severity level threshold, a "
        "traveler response status, an incident type, or a time condition."
    ),
    valid_source_types=[
        "Service", "ContactRole", "Obligation", "Alert", "Workflow",
    ],
    valid_target_types=[
        "SeverityLevel", "TravelerResponseStatus", "Incident", "RiskCategory",
    ],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse to find what conditions must be met for an action to apply. "
        "From a Service or ContactRole, follow CONDITIONAL_ON to find the "
        "severity levels, response statuses, or incident types that gate it."
    ),
)

STEP_OF = RelationshipSchema(
    type="STEP_OF",
    description=(
        "A service, alert, or obligation is a step within a named workflow."
    ),
    valid_source_types=["Service", "Alert", "Obligation"],
    valid_target_types=["Workflow"],
    cardinality="many_to_one",
    is_directed=True,
    mandatory=False,
    agent_traversal_hint=(
        "Traverse from a workflow step to its parent workflow, or from a "
        "Workflow to enumerate all its component steps."
    ),
)


def _discover_relationship_schemas() -> list[RelationshipSchema]:
    """Find all RelationshipSchema instances defined at module level."""
    import sys

    module = sys.modules[__name__]
    schemas: list[RelationshipSchema] = []
    seen_ids: set[int] = set()
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, RelationshipSchema) and id(obj) not in seen_ids:
            seen_ids.add(id(obj))
            schemas.append(obj)
    schemas.sort(key=lambda s: s.type)
    return schemas


RELATIONSHIP_SCHEMAS: list[RelationshipSchema] = _discover_relationship_schemas()

# Multiple schemas can share the same type (e.g. CONTAINS has two variants
# with different source/target constraints). The map stores all of them.
RELATIONSHIP_TYPE_MAP: dict[str, list[RelationshipSchema]] = {}
for _rs in RELATIONSHIP_SCHEMAS:
    RELATIONSHIP_TYPE_MAP.setdefault(_rs.type, []).append(_rs)

VALID_RELATIONSHIP_TYPES: set[str] = set(RELATIONSHIP_TYPE_MAP.keys())


# ============================================================
# PROMPT AUTO-GENERATION
# ============================================================


def _python_type_to_json_type(annotation: Any) -> str:
    """Map a Python type annotation to a human-readable JSON type string."""
    if annotation is str:
        return "string"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"

    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        if args:
            inner = _python_type_to_json_type(args[0])
            return f"array of {inner}"
        return "array"
    if origin is dict:
        return "object"
    if origin is Union:
        args = get_args(annotation)
        # Handle Optional[X] = Union[X, None]
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _python_type_to_json_type(non_none[0]) + " (optional)"
        return " | ".join(_python_type_to_json_type(a) for a in non_none)

    return "string"


def generate_entity_type_prompt_section() -> str:
    """Auto-generate the 'Entity Types' section of the extraction prompt.

    For each registered type, emits:
    - Type name and description (from class docstring)
    - Required/optional typed attribute fields with descriptions
    """
    base_fields = set(BaseEntitySchema.model_fields.keys())
    lines = [
        "Classify each entity using one of these types based on what the "
        "text describes:\n"
    ]

    for cls in ENTITY_TYPE_CLASSES:
        type_name = cls.model_fields["type"].default
        doc = (cls.__doc__ or "").strip()
        lines.append(f"- **{type_name}**: {doc}")

        # Get typed attributes (fields not in BaseEntitySchema)
        typed_fields = {
            k: v for k, v in cls.model_fields.items() if k not in base_fields
        }

        if typed_fields:
            attrs = ", ".join(
                f"{fn} ({_python_type_to_json_type(fi.annotation)})"
                for fn, fi in typed_fields.items()
            )
            lines.append(f"  Attributes: {attrs}")

        lines.append("")

    # Add forbidden types warning
    if FORBIDDEN_TYPE_ALIASES:
        forbidden_names = ", ".join(sorted(FORBIDDEN_TYPE_ALIASES.keys()))
        examples = []
        for bad, good in sorted(FORBIDDEN_TYPE_ALIASES.items()):
            if bad != good:
                examples.append(f"{bad} → {good}")
        examples_str = ", ".join(examples[:5])
        lines.append(
            f"**IMPORTANT**: The following are NOT valid entity types — do not "
            f"use them: {forbidden_names}. Use the types listed above instead "
            f"(e.g., {examples_str})."
        )

    return "\n".join(lines)


def generate_entity_type_prompt_section_slim() -> str:
    """Auto-generate a slim 'Entity Types' section with type names and descriptions only.

    Unlike generate_entity_type_prompt_section(), this does NOT include typed
    attribute fields. Used by the entity-only extraction pass to reduce prompt
    size — entities are extracted with base fields only (id, type, name,
    description, source_anchor).
    """
    lines = [
        "Classify each entity using one of these types based on what the "
        "text describes:\n"
    ]

    for cls in ENTITY_TYPE_CLASSES:
        type_name = cls.model_fields["type"].default
        doc = (cls.__doc__ or "").strip()
        lines.append(f"- **{type_name}**: {doc}")

    lines.append("")

    # Add forbidden types warning
    if FORBIDDEN_TYPE_ALIASES:
        forbidden_names = ", ".join(sorted(FORBIDDEN_TYPE_ALIASES.keys()))
        examples = []
        for bad, good in sorted(FORBIDDEN_TYPE_ALIASES.items()):
            if bad != good:
                examples.append(f"{bad} → {good}")
        examples_str = ", ".join(examples[:5])
        lines.append(
            f"**IMPORTANT**: The following are NOT valid entity types — do not "
            f"use them: {forbidden_names}. Use the types listed above instead "
            f"(e.g., {examples_str})."
        )

    return "\n".join(lines)


def generate_entity_structure_prompt_section(
    id_prefix: str, section_number: str
) -> str:
    """Auto-generate the 'Entity Structure' section showing per-type JSON shapes.

    Replaces the old generic attributes:{} structure with typed fields.
    """
    base_fields = set(BaseEntitySchema.model_fields.keys())

    if id_prefix:
        id_lines = [
            "**id** (required)",
            f"- Format: Start with the prefix `{id_prefix}_` followed by a "
            "descriptive identifier",
            "- Use lowercase with underscores",
            "- Make it descriptive of the entity content",
            f"- Example: `{id_prefix}_role_stakeholders` or "
            f"`{id_prefix}_doc_policy`\n",
        ]
    else:
        id_lines = [
            "**id** (required)",
            "- Use a plain descriptive identifier in lowercase with underscores",
            "- Make it descriptive of the entity content",
            "- Example: `coach_class_requirement` or "
            "`executive_director`\n",
        ]

    lines = [
        "Create each entity with the following fields:\n",
        *id_lines,
        "**type** (required)",
        "- Must be one of the entity types listed above\n",
        "**name** (required)",
        "- A clear, human-readable name for this entity",
        "- Should be concise but descriptive\n",
        "**description** (required)",
        "- A brief description of what this entity represents",
        "- Draw this from the policy text",
        "- For named entities from lists, reference the parent sentence "
        "context\n",
    ]

    # Show typed attributes section
    has_any_typed = False
    for cls in ENTITY_TYPE_CLASSES:
        typed_fields = {
            k: v for k, v in cls.model_fields.items() if k not in base_fields
        }
        if typed_fields:
            has_any_typed = True
            break

    if has_any_typed:
        lines.append("**Typed attributes** (per entity type)")
        lines.append(
            "- Each entity type has specific typed attribute fields. "
            "Populate the fields defined for that type."
        )
        lines.append(
            "- String fields not present in source text: use \"\" (empty string)\n"
            "- Number/integer fields not present (optional): use null\n"
            "- Boolean fields: always provide true or false\n"
            "- Array fields not present: use [] (empty array)"
        )
        lines.append(
            "- Do NOT add arbitrary key-value attributes outside the "
            "defined fields for each type.\n"
        )
    else:
        lines.append("**attributes** (required)")
        lines.append(
            "- A dictionary of specific key-value pairs capturing concrete "
            "values"
        )
        lines.append(
            "- Include numbers, dates, emails, thresholds, lists found in "
            "the text"
        )
        lines.append(
            "- If no specific values are present, use an empty object: {{}}\n"
        )

    lines.append("**source_anchor** (required)")
    lines.append("- This is a mandatory object with two fields:")
    lines.append(
        "  - **source_text**: The EXACT verbatim quote from the section text "
        "that supports this entity. Copy character-for-character from the "
        "source. Do NOT paraphrase. For named entities from lists, use the "
        "complete parent sentence that introduces the list."
    )
    lines.append(f"  - **source_section**: Must be set to `{section_number}`")

    return "\n".join(lines)


def generate_json_output_example() -> str:
    """Auto-generate a JSON output example showing per-type attribute shapes."""
    base_fields = set(BaseEntitySchema.model_fields.keys())
    lines = []

    # Find a type with typed attributes for the example, or use first type
    example_cls = ENTITY_TYPE_CLASSES[0]
    for cls in ENTITY_TYPE_CLASSES:
        typed_fields = {
            k: v for k, v in cls.model_fields.items() if k not in base_fields
        }
        if typed_fields:
            example_cls = cls
            break

    type_name = example_cls.model_fields["type"].default
    typed_fields = {
        k: v
        for k, v in example_cls.model_fields.items()
        if k not in base_fields
    }

    # Build example entity JSON
    lines.append("```json")
    lines.append("{")
    lines.append('  "entities": [')
    lines.append("    {")
    lines.append(f'      "id": "s01_example_{type_name.lower()}",')
    lines.append(f'      "type": "{type_name}",')
    lines.append(f'      "name": "Example {type_name}",')
    lines.append(f'      "description": "Description from the policy text",')

    if typed_fields:
        for i, (field_name, field_info) in enumerate(typed_fields.items()):
            type_str = _python_type_to_json_type(field_info.annotation)
            is_optional = "optional" in type_str
            if "array" in type_str:
                val = "[]"
            elif is_optional:
                val = "null"
            elif "integer" in type_str or "number" in type_str:
                val = "0"
            elif "boolean" in type_str:
                val = "false"
            else:
                val = '""'
            comma = "," if i < len(typed_fields) - 1 else ","
            lines.append(f'      "{field_name}": {val}{comma}')
    else:
        lines.append('      "attributes": {},')

    lines.append('      "source_anchor": {')
    lines.append('        "source_text": "Exact verbatim quote",')
    lines.append('        "source_section": "SEC-XX"')
    lines.append("      }")
    lines.append("    }")
    lines.append("  ],")
    lines.append('  "relationships": [')
    lines.append("    {")
    lines.append('      "source_id": "s01_entity_a",')
    lines.append('      "target_id": "s01_entity_b",')
    lines.append('      "type": "requires",')
    lines.append('      "description": "Entity A requires Entity B"')
    lines.append("    }")
    lines.append("  ]")
    lines.append("}")
    lines.append("```")

    return "\n".join(lines)


def generate_example_entity(section_id: str = "SEC-XX") -> str:
    """Generate a fake example entity JSON for injection into the extraction prompt.

    Picks the first entity type class with typed attributes, creates a dict with
    placeholder values for every field, and returns a formatted JSON string.
    """
    import json as _json

    base_fields = set(BaseEntitySchema.model_fields.keys())

    # Pick the first type with typed attributes
    example_cls = ENTITY_TYPE_CLASSES[0]
    for cls in ENTITY_TYPE_CLASSES:
        typed_fields = {
            k: v for k, v in cls.model_fields.items() if k not in base_fields
        }
        if typed_fields:
            example_cls = cls
            break

    type_name = example_cls.model_fields["type"].default
    typed_fields = {
        k: v for k, v in example_cls.model_fields.items() if k not in base_fields
    }

    entity: dict = {
        "id": f"example_{type_name.lower()}",
        "type": type_name,
        "name": f"Example {type_name}",
        "description": "Description drawn from the policy text",
    }

    for field_name, field_info in typed_fields.items():
        type_str = _python_type_to_json_type(field_info.annotation)
        is_optional = "optional" in type_str
        if "array" in type_str:
            entity[field_name] = []
        elif is_optional:
            entity[field_name] = None
        elif "integer" in type_str or "number" in type_str:
            entity[field_name] = 0
        elif "boolean" in type_str:
            entity[field_name] = False
        else:
            entity[field_name] = ""

    entity["source_anchor"] = {
        "source_text": "Exact verbatim quote from section text",
        "source_section": section_id,
    }

    return _json.dumps(entity, indent=4)


def generate_example_relationship() -> str:
    """Generate a fake example relationship JSON for injection into the extraction prompt.

    Picks the first relationship schema and creates a placeholder relationship dict.
    """
    import json as _json

    if RELATIONSHIP_SCHEMAS:
        rs = RELATIONSHIP_SCHEMAS[0]
        rel_type = rs.type
    else:
        rel_type = "CONTAINS"

    rel = {
        "source_id": "entity_a",
        "target_id": "entity_b",
        "type": rel_type,
        "description": f"Entity A {rel_type.lower().replace('_', ' ')} Entity B",
    }

    return _json.dumps(rel, indent=4)


def generate_relationship_type_prompt_section() -> str:
    """Auto-generate the 'Relationship Types' section of the extraction prompt.

    For each registered type, emits:
    - Relationship type name and description
    - Valid source -> target type constraints (if any)
    """
    if not RELATIONSHIP_SCHEMAS:
        # Fallback: no relationship schemas registered yet.
        # Return a minimal section that doesn't constrain types.
        return (
            "Use descriptive relationship types that capture the semantic "
            "connection between entities. Common types include: requires, "
            "applies_to, triggers, escalates_to, prohibits, permits, "
            "provides, classified_as, managed_by, part_of, references, "
            "implements, reports_to, responsible_for, specifies, "
            "requires_approval_from, must_comply_with, mitigates."
        )

    lines = [
        "Use ONLY these relationship types. Each has specific constraints "
        "on which entity types can be the source and target:\n"
    ]

    # Deduplicate same-type relationships (e.g. two CONTAINS variants)
    # by merging their source/target constraints into one line.
    seen: dict[str, tuple[set[str], set[str]]] = {}
    for rs in RELATIONSHIP_SCHEMAS:
        if rs.type not in seen:
            seen[rs.type] = (set(rs.valid_source_types), set(rs.valid_target_types))
        else:
            seen[rs.type][0].update(rs.valid_source_types)
            seen[rs.type][1].update(rs.valid_target_types)

    for rel_type, (sources, targets) in seen.items():
        source_str = ", ".join(sorted(sources)) if sources else "any"
        target_str = ", ".join(sorted(targets)) if targets else "any"
        lines.append(f"- **{rel_type}**: [{source_str}] → [{target_str}]")

    return "\n".join(lines)


# ============================================================
# VALIDATION
# ============================================================


def get_typed_attributes(entity: BaseEntitySchema) -> dict[str, Any]:
    """Extract type-specific fields + any __pydantic_extra__ overflow.

    model_dump() merges __pydantic_extra__ at top level alongside typed
    fields, so we just exclude the base fields that every entity shares.

    Returns a flat dict of attribute name -> value.
    """
    base_fields = set(BaseEntitySchema.model_fields.keys())
    return {
        k: v for k, v in entity.model_dump().items() if k not in base_fields
    }


def validate_entity(
    entity_data: dict,
) -> tuple[BaseEntitySchema | None, list[str]]:
    """Validate a raw entity dict against the typed schemas.

    Failure policy:
    - Unknown type:                          (None, [warning])
    - Missing required base fields:          (None, [error per field])
    - Field type mismatch (coercion fails):  (None, [error])
    - All required present, extra fields:    (entity, [warnings])
    - Missing optional typed attributes:     (entity, []) — clean

    All callers treat None as "skip this entity and log the warning."
    """
    warnings: list[str] = []
    entity_type = entity_data.get("type", "")

    if entity_type not in VALID_ENTITY_TYPES:
        # Check if it's a forbidden alias
        if entity_type in FORBIDDEN_TYPE_ALIASES:
            correct = FORBIDDEN_TYPE_ALIASES[entity_type]
            return None, [
                f"Forbidden entity type '{entity_type}' — should be "
                f"'{correct}'. Entity skipped."
            ]
        return None, [
            f"Unknown entity type: '{entity_type}'. "
            f"Valid types: {sorted(VALID_ENTITY_TYPES)}. Entity skipped."
        ]

    cls = ENTITY_TYPE_MAP[entity_type]

    # Check for extra fields not in the typed schema
    base_fields = set(BaseEntitySchema.model_fields.keys())
    typed_fields = set(cls.model_fields.keys())
    all_known_fields = base_fields | typed_fields
    extra_keys = set(entity_data.keys()) - all_known_fields
    if extra_keys:
        warnings.append(
            f"Extra field(s) not in {entity_type} schema: "
            f"{sorted(extra_keys)}"
        )

    try:
        entity = cls(**entity_data)
        return entity, warnings
    except ValidationError as e:
        errors = []
        for err in e.errors():
            field = ".".join(str(loc) for loc in err["loc"])
            msg = err["msg"]
            errors.append(f"{entity_type} validation error on '{field}': {msg}")
        return None, errors


def validate_relationship(
    rel_type: str,
    source_id: str,
    target_id: str,
    entity_type_lookup: dict[str, str],
) -> list[str]:
    """Validate a relationship against schema constraints.

    Checks:
    - rel type is in VALID_RELATIONSHIP_TYPES (if registry is populated)
    - source entity type is in valid_source_types (if constrained)
    - target entity type is in valid_target_types (if constrained)

    Returns list of warning strings (empty = valid).
    """
    if not RELATIONSHIP_SCHEMAS:
        # No relationship schemas registered — skip validation
        return []

    warnings: list[str] = []

    if rel_type not in VALID_RELATIONSHIP_TYPES:
        warnings.append(
            f"Unknown relationship type: '{rel_type}'. "
            f"Valid types: {sorted(VALID_RELATIONSHIP_TYPES)}"
        )
        return warnings

    schemas = RELATIONSHIP_TYPE_MAP[rel_type]
    source_type = entity_type_lookup.get(source_id, "Unknown")
    target_type = entity_type_lookup.get(target_id, "Unknown")

    # A relationship is valid if ANY schema variant for this type matches.
    # (e.g. CONTAINS has Policy->PolicySection and PolicySection->PolicyRule)
    for schema in schemas:
        source_ok = (
            not schema.valid_source_types
            or source_type in schema.valid_source_types
        )
        target_ok = (
            not schema.valid_target_types
            or target_type in schema.valid_target_types
        )
        if source_ok and target_ok:
            return []  # Valid against this variant

    # No variant matched — build warning from all variants' constraints
    all_source_types = sorted({
        t for s in schemas for t in s.valid_source_types
    })
    all_target_types = sorted({
        t for s in schemas for t in s.valid_target_types
    })

    if all_source_types and source_type not in all_source_types:
        warnings.append(
            f"Relationship '{rel_type}': source '{source_id}' has type "
            f"'{source_type}', not in valid source types "
            f"{all_source_types}"
        )

    if all_target_types and target_type not in all_target_types:
        warnings.append(
            f"Relationship '{rel_type}': target '{target_id}' has type "
            f"'{target_type}', not in valid target types "
            f"{all_target_types}"
        )

    return warnings


def reconstruct_merged_entity(
    merged_dict: dict,
    source_entities: list[BaseEntitySchema],
) -> tuple[BaseEntitySchema | None, list[str]]:
    """Reconstruct a typed entity from LLM dedup output.

    Wraps validate_entity() with merge-specific checks:
    1. Warns if typed attribute field present in ALL source entities
       is absent from merged_dict (LLM dropped data during merge)
    2. Warns if merged type differs from source entity types
       (LLM changed the type — almost always wrong)
    3. Verifies merged ID is a valid canonical ID
    """
    warnings: list[str] = []
    merged_type = merged_dict.get("type", "")

    # Check 2: Type change detection
    source_types = {e.type for e in source_entities}
    if source_types and merged_type not in source_types:
        warnings.append(
            f"Merged entity type '{merged_type}' differs from source types "
            f"{source_types}. LLM may have incorrectly changed the type."
        )

    # Check 1: Dropped typed attributes
    if merged_type in ENTITY_TYPE_MAP and source_entities:
        cls = ENTITY_TYPE_MAP[merged_type]
        base_fields = set(BaseEntitySchema.model_fields.keys())
        typed_field_names = {
            k for k in cls.model_fields.keys() if k not in base_fields
        }

        for field_name in typed_field_names:
            # Check if ALL source entities had a non-empty value for this field
            all_sources_have = all(
                getattr(e, field_name, None)
                for e in source_entities
                if hasattr(e, field_name)
            )
            if all_sources_have and field_name not in merged_dict:
                warnings.append(
                    f"Typed attribute '{field_name}' present in all source "
                    f"entities but absent from merged output. "
                    f"LLM may have dropped data during merge."
                )

    # Check 3: ID continuity
    merged_id = merged_dict.get("id", "")
    source_ids = {e.id for e in source_entities}
    if merged_id and source_ids and merged_id not in source_ids:
        # New canonical ID is fine — just note it
        log.debug(
            "Merged entity ID '%s' is a new canonical ID (sources: %s)",
            merged_id,
            source_ids,
        )

    # Delegate to validate_entity for actual construction
    entity, validation_warnings = validate_entity(merged_dict)
    warnings.extend(validation_warnings)

    return entity, warnings
