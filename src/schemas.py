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
from enum import Enum
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


# ============================================================
# TYPED ENTITY SCHEMAS
# Stubs — user fills in typed attribute fields on each subclass.
# All typed fields MUST have defaults so partial extraction doesn't fail.
# Use Field(description="...") on every attribute for prompt generation.
# ============================================================

# ============================================================
# GROUP 1: CORE POLICY ENTITIES
# ============================================================


class PolicyEntity(BaseEntitySchema):
    """The top-level travel policy document that governs all travel behavior
    for an organization. Acts as the root node of the policy graph — all
    sections, rules, and exceptions trace back to this entity.
    """

    type: Literal["Policy"] = "Policy"

    version: str = Field(
        default="",
        description=(
            "The version or revision identifier of the policy document "
            "(e.g. '1.0', '2024-Q1'). Used to distinguish between iterations "
            "of the same policy over time."
        ),
    )
    effective_date: str = Field(
        default="",
        description=(
            "The date on which this policy became or becomes active. "
            "Format as ISO 8601 (YYYY-MM-DD) where possible."
        ),
    )
    issuing_organization: str = Field(
        default="",
        description=(
            "The name of the organization that authored and enforces this policy. "
            "This should match the Organization entity name where one exists in the graph."
        ),
    )
    jurisdiction: str = Field(
        default="",
        description=(
            "The geographic or organizational scope within which this policy applies "
            "(e.g. 'United States', 'Global', 'North America', 'All Employees')."
        ),
    )
    last_reviewed_by: str = Field(
        default="",
        description=(
            "The role or name of the individual or body responsible for the most "
            "recent review or update of this policy (e.g. 'Executive Director', "
            "'Board of Directors')."
        ),
    )


class PolicySectionEntity(BaseEntitySchema):
    """A major thematic section within a travel policy document. Sections
    group related rules under a common topic (e.g. Air Travel, Lodging,
    Meals). They act as intermediate nodes between the Policy root and
    individual PolicyRule leaf nodes.
    """

    type: Literal["PolicySection"] = "PolicySection"

    section_order: int = Field(
        default=0,
        description=(
            "The ordinal position of this section within the parent policy document. "
            "Used to reconstruct the document's original structure and to resolve "
            "ordering conflicts when multiple sections address related topics."
        ),
    )
    parent_policy_id: str = Field(
        default="",
        description=(
            "The id of the Policy entity that this section belongs to. "
            "Establishes the CONTAINS relationship from Policy to PolicySection."
        ),
    )
    topic: str = Field(
        default="",
        description=(
            "The high-level subject matter of this section "
            "(e.g. 'Air Travel', 'Lodging', 'Meals and Entertainment', "
            "'Car Rentals', 'Telecommunications'). Used for semantic routing "
            "when matching a travel event to the relevant policy area."
        ),
    )


class PolicyRuleEntity(BaseEntitySchema):
    """A single, discrete, actionable rule extracted from a travel policy.
    Represents the atomic unit of policy enforcement. Each rule should
    express exactly one behavioral constraint, obligation, or permission.
    Rules are the primary nodes evaluated by the agent when determining
    compliance or resolving a travel disruption.
    """

    type: Literal["PolicyRule"] = "PolicyRule"

    rule_text: str = Field(
        default="",
        description=(
            "The verbatim or faithfully paraphrased text of the rule as it appears "
            "in the source policy document. Should be self-contained and interpretable "
            "without additional context where possible."
        ),
    )
    rule_type: str = Field(
        default="",
        description=(
            "The behavioral classification of this rule. Must be one of: "
            "'mandatory' (the traveler must comply), "
            "'recommended' (the traveler is encouraged to comply), or "
            "'prohibited' (the traveler must not do this). "
            "This field drives enforcement logic in the agent."
        ),
    )
    enforcement_level: str = Field(
        default="",
        description=(
            "How strictly this rule is enforced in practice. Must be one of: "
            "'strict' (no deviation without written approval) or "
            "'discretionary' (judgment-based deviation is acceptable). "
            "Infer from language such as 'must', 'required', 'should', 'encouraged'."
        ),
    )
    parent_section_id: str = Field(
        default="",
        description=(
            "The id of the PolicySection entity that this rule belongs to. "
            "Establishes the CONTAINS relationship from PolicySection to PolicyRule."
        ),
    )
    is_default: bool = Field(
        default=False,
        description=(
            "Whether this rule represents a default behavior that applies in the "
            "absence of other conditions (e.g. 'a standard non-smoking room is "
            "automatically reserved'). Default rules may be overridden by exceptions "
            "or more specific rules."
        ),
    )


class PolicyExceptionEntity(BaseEntitySchema):
    """A formally defined deviation from a standard PolicyRule. Exceptions
    establish the conditions under which normal rules do not apply and what
    alternative behavior is permitted or required instead. Exception nodes
    are critical for the agent to correctly handle edge cases without
    incorrectly flagging compliant-but-unusual traveler behavior as a
    violation.
    """

    type: Literal["PolicyException"] = "PolicyException"

    exception_type: str = Field(
        default="",
        description=(
            "The category of this exception. Must be one of: "
            "'pre-approved' (blanket permission granted in advance, no per-instance approval needed), "
            "'conditional' (permitted only when a specific condition is met), or "
            "'emergency' (permitted only in urgent or unforeseeable circumstances). "
            "This field determines the approval workflow the agent must trigger."
        ),
    )
    approval_required: bool = Field(
        default=True,
        description=(
            "Whether this exception requires explicit authorization from a Stakeholder "
            "before it can be exercised. If True, the agent must surface an approval "
            "Requirement before allowing the excepted behavior."
        ),
    )
    parent_rule_id: str = Field(
        default="",
        description=(
            "The id of the PolicyRule entity that this exception modifies or overrides. "
            "Establishes the HAS_EXCEPTION relationship from PolicyRule to PolicyException."
        ),
    )
    permitted_behavior: str = Field(
        default="",
        description=(
            "A description of what the traveler is allowed to do under this exception "
            "that would otherwise violate the parent rule "
            "(e.g. 'travel in business class when pre-approved by Executive Director'). "
            "Used by the agent to determine the compliant alternative action."
        ),
    )
    triggering_condition: str = Field(
        default="",
        description=(
            "The circumstance or condition that makes this exception applicable "
            "(e.g. 'free upgrade offered by carrier', 'emergency situation', "
            "'prior written approval obtained'). Should map to or reference "
            "a Constraint entity where one exists."
        ),
    )

# ============================================================
# ENUMS
# Constrained value sets for Actor & Stakeholder entity fields.
# ============================================================


class TravelerRoleType(str, Enum):
    EMPLOYEE = "Employee"
    BOARD_MEMBER = "BoardMember"
    SITE_VISITOR = "SiteVisitor"
    CONTRACTOR = "Contractor"
    VOLUNTEER = "Volunteer"
    UNKNOWN = "Unknown"


class AuthorityLevel(str, Enum):
    EXECUTIVE = "Executive"
    MANAGEMENT = "Management"
    STAFF = "Staff"
    EXTERNAL = "External"


class ServiceType(str, Enum):
    TRAVEL_AGENT = "TravelAgent"
    HOTEL = "Hotel"
    CAR_RENTAL = "CarRental"
    AIRLINE = "Airline"
    RAIL = "Rail"
    SHUTTLE = "Shuttle"
    OTHER = "Other"


class MandateType(str, Enum):
    REQUIRED = "Required"
    PREFERRED = "Preferred"


# ============================================================
# GROUP 2: ACTOR & STAKEHOLDER ENTITY SCHEMAS
# ============================================================


class TravelerRoleEntity(BaseEntitySchema):
    """A category of person covered by the travel policy.

    Represents the different classifications of individuals who
    may travel on behalf of the organization and are subject to
    the rules defined within the travel policy. Different roles
    may have different rules, limits, and reimbursement conditions
    applied to them.

    Examples: Employee, BoardMember, SiteVisitor, Contractor, Volunteer.
    """

    type: Literal["TravelerRole"] = "TravelerRole"

    role_name: TravelerRoleType = Field(
        default=TravelerRoleType.UNKNOWN,
        description=(
            "The specific classification of the traveler as defined by the policy. "
            "Must be one of: Employee, BoardMember, SiteVisitor, Contractor, Volunteer. "
            "Use Unknown if the role is referenced but not clearly classifiable."
        ),
    )
    coverage_scope: str = Field(
        default="",
        description=(
            "A description of the breadth of policy coverage for this role — "
            "which sections, expense types, or rules explicitly apply to or "
            "exclude this traveler category."
        ),
    )
    receipt_requirement_threshold: Optional[float] = Field(
        default=None,
        description=(
            "The minimum expense amount in USD above which receipts are required "
            "for this traveler role. None if all expenses require receipts regardless "
            "of amount, as is the case for SiteVisitors."
        ),
    )
    expense_report_deadline_days: Optional[int] = Field(
        default=None,
        description=(
            "The number of days after the conclusion of travel within which this "
            "traveler role must submit a completed expense report."
        ),
    )


class StakeholderEntity(BaseEntitySchema):
    """An internal party with defined responsibilities under the travel policy.

    Represents individuals or departments within the organization
    that hold specific duties related to the administration, enforcement,
    approval, or maintenance of the travel policy. Stakeholders are
    key nodes for routing approval requirements and resolving travel events
    autonomously — the agent must know who to contact or escalate to when
    a policy rule is triggered.

    Examples: Executive Director, Accounting Department,
    Board of Directors Chair, Treasurer, Marketing Specialist.
    """

    type: Literal["Stakeholder"] = "Stakeholder"

    department: str = Field(
        default="",
        description=(
            "The organizational department or team this stakeholder belongs to. "
            "For named individuals, this is their functional area "
            "(e.g., Finance, Marketing, Executive Leadership)."
        ),
    )
    authority_level: AuthorityLevel = Field(
        default=AuthorityLevel.STAFF,
        description=(
            "The level of organizational authority this stakeholder holds. "
            "Must be one of: Executive, Management, Staff, External. "
            "Authority level determines the weight of approvals they can grant."
        ),
    )
    responsibilities: list[str] = Field(
        default=[],
        description=(
            "A list of distinct responsibilities this stakeholder holds under the "
            "travel policy. Each item should be a discrete duty "
            "(e.g., 'Approve exceptions to travel policy', "
            "'Ensure policy is distributed to new employees', "
            "'Process extra night hotel billing after board meetings')."
        ),
    )
    can_grant_exceptions: bool = Field(
        default=False,
        description=(
            "Whether this stakeholder has the authority to grant written approval "
            "for exceptions or deviations from standard policy rules."
        ),
    )
    policy_maintenance_role: bool = Field(
        default=False,
        description=(
            "Whether this stakeholder holds any responsibility for maintaining, "
            "updating, or collaborating on revisions to the travel policy document."
        ),
    )


class ServiceProviderEntity(BaseEntitySchema):
    """An external vendor or service provider referenced or mandated by the travel policy.

    Represents third-party companies or individuals that travelers
    are required or encouraged to use when arranging travel. These nodes
    are critical for the agentic use case — when a travel event occurs,
    the agent must know which provider to engage, whether use is mandatory,
    and what service they cover.

    Examples: Regency Travel (travel agent), corporate hotel chains,
    car rental companies.
    """

    type: Literal["ServiceProvider"] = "ServiceProvider"

    service_type: ServiceType = Field(
        default=ServiceType.OTHER,
        description=(
            "The category of service this provider delivers. "
            "Must be one of: TravelAgent, Hotel, CarRental, Airline, Rail, Shuttle, Other."
        ),
    )
    contact_info: str = Field(
        default="",
        description=(
            "Any contact details for this provider as stated in the policy document, "
            "including phone numbers, email addresses, or named contact persons "
            "(e.g., 'Cindy Mielke at Regency Travel; 888-386-1036')."
        ),
    )
    mandate_type: MandateType = Field(
        default=MandateType.PREFERRED,
        description=(
            "Whether the policy requires use of this provider or merely recommends it. "
            "Required means travelers must use this provider to qualify for reimbursement. "
            "Preferred means use is encouraged but alternatives are permitted."
        ),
    )
    covers_expense_categories: list[str] = Field(
        default=[],
        description=(
            "The expense categories this provider is responsible for servicing "
            "under the policy (e.g., ['Airfare', 'Lodging'] for a travel agent). "
            "Use the canonical ExpenseCategory names where possible."
        ),
    )
    billing_arrangement: str = Field(
        default="",
        description=(
            "How this provider is paid under the policy — whether expenses are "
            "billed directly to a corporate account, charged to a corporate credit card, "
            "or reimbursed to the traveler after the fact."
        ),
    )


# ============================================================
# GROUP 3: TRAVEL OPTION & CONTEXT ENTITIES
# ============================================================

class TransportationModeEntity(BaseEntitySchema):
    """A method of travel available to or governed by the policy."""

    type: Literal["TransportationMode"] = "TransportationMode"

    mode_name: str = Field(
        default="",
        description=(
            "The canonical name of the transportation mode. "
            "Expected values: CommercialAir, Rail, CarRental, PersonalVehicle, "
            "Taxi, Shuttle, PublicTransit."
        ),
    )
    is_restricted: bool = Field(
        default=False,
        description=(
            "Whether this mode has explicit restrictions or requires pre-approval "
            "before use under the policy."
        ),
    )
    reimbursement_basis: str = Field(
        default="",
        description=(
            "The basis on which costs for this mode are reimbursed. "
            "E.g. 'lowest available fare', 'GSA mileage rate', 'actual cost', "
            "'most economical available'."
        ),
    )
    booking_channel: str = Field(
        default="",
        description=(
            "The required or preferred channel through which this mode must be booked. "
            "E.g. 'designated travel agent', 'direct', 'any'."
        ),
    )
    conditions_for_use: str = Field(
        default="",
        description=(
            "Plain-language description of the conditions under which this "
            "transportation mode is permitted or preferred over alternatives. "
            "E.g. 'only when other modes are unavailable, more costly, or impractical'."
        ),
    )


class ClassOfServiceEntity(BaseEntitySchema):
    """A service tier within a transportation mode, such as coach or economy class."""

    type: Literal["ClassOfService"] = "ClassOfService"

    tier_name: str = Field(
        default="",
        description=(
            "The name of the service tier. "
            "Expected values: Coach, Economy, Business, First, Intermediate, Premium."
        ),
    )
    parent_mode: str = Field(
        default="",
        description=(
            "The name or ID of the TransportationMode entity this class of service "
            "belongs to. E.g. 'CommercialAir', 'Rail'."
        ),
    )
    is_default: bool = Field(
        default=False,
        description=(
            "Whether this class of service is the default required tier "
            "for all travelers under the policy."
        ),
    )
    requires_approval: bool = Field(
        default=False,
        description=(
            "Whether booking this class of service requires prior written approval "
            "from an authorized stakeholder."
        ),
    )
    upgrade_allowed: bool = Field(
        default=False,
        description=(
            "Whether travelers may use this class of service if a complimentary "
            "upgrade is provided at no incremental cost to the organization."
        ),
    )
    is_prohibited: bool = Field(
        default=False,
        description=(
            "Whether this class of service is explicitly prohibited under the policy "
            "unless an exception is granted."
        ),
    )


class AccommodationEntity(BaseEntitySchema):
    """A lodging type or option governed by the travel policy."""

    type: Literal["Accommodation"] = "Accommodation"

    accommodation_type: str = Field(
        default="",
        description=(
            "The category of accommodation. "
            "Expected values: Hotel, Motel."
        ),
    )
    room_type: str = Field(
        default="",
        description=(
            "The default or standard room type to be booked under the policy. "
            "Expected values: Standard, Suite."
        ),
    )
    is_default: bool = Field(
        default=False,
        description=(
            "Whether this accommodation and room type combination represents "
            "the default that should be booked unless otherwise specified."
        ),
    )
    smoking_preference: str = Field(
        default="",
        description=(
            "The default smoking preference applied when booking rooms. "
            "Expected values: NonSmoking, Smoking, NoPreference."
        ),
    )
    booking_channel: str = Field(
        default="",
        description=(
            "The required or preferred channel for booking this accommodation. "
            "E.g. 'designated travel agent', 'master rooming list', "
            "'program-booked', 'self-booked'."
        ),
    )
    nightly_rate_limit: Optional[float] = Field(
        default=None,
        description=(
            "The maximum nightly room rate in USD that is reimbursable without "
            "requiring additional approval. E.g. 175.00."
        ),
    )
    cancellation_policy: str = Field(
        default="",
        description=(
            "Plain-language description of the cancellation obligation placed "
            "on the traveler. E.g. 'must cancel by deadline or obtain cancellation number'."
        ),
    )


class BusinessContextEntity(BaseEntitySchema):
    """The organizational purpose for which business travel is being undertaken.
    Determines which subset of policy rules are applicable to a given trip."""

    type: Literal["BusinessContext"] = "BusinessContext"

    context_name: str = Field(
        default="",
        description=(
            "The name of the business travel context or purpose. "
            "Expected values: BoardMeeting, SiteVisit, Exhibit, Conference, "
            "ClientVisit, TradeShow."
        ),
    )
    context_category: str = Field(
        default="",
        description=(
            "Whether the travel context is internal to the organization or involves "
            "an external party. Expected values: internal, external."
        ),
    )
    coordinator_role: str = Field(
        default="",
        description=(
            "The role of the stakeholder responsible for coordinating travel "
            "arrangements for this context. "
            "E.g. 'Executive Director', 'Marketing Specialist', 'IAC Director of Marketing'."
        ),
    )
    has_master_billing: bool = Field(
        default=False,
        description=(
            "Whether expenses for this travel context are centrally billed "
            "to an organizational master account rather than individually reimbursed."
        ),
    )
    eligible_traveler_roles: str = Field(
        default="",
        description=(
            "Comma-separated list of TravelerRole names that are eligible to "
            "travel under this business context. "
            "E.g. 'Employee, Volunteer, BoardMember'."
        ),
    )
    pre_approval_required: bool = Field(
        default=False,
        description=(
            "Whether travel undertaken for this business context requires "
            "pre-approval before arrangements can be made."
        ),
    )


class TravelEventEntity(BaseEntitySchema):
    """A disruption, change, or notable occurrence that arises during a travel itinerary
    and may trigger one or more policy rules or downstream cascading events.
    This is the primary entry point for agentic policy reasoning."""

    type: Literal["TravelEvent"] = "TravelEvent"

    event_type: str = Field(
        default="",
        description=(
            "The category of the travel disruption or change. "
            "Expected values: Cancellation, Rebooking, Upgrade, Delay, NoShow, "
            "Emergency, MissedConnection, OverbookingDisplacement."
        ),
    )
    initiator: str = Field(
        default="",
        description=(
            "The party or cause responsible for triggering the event. "
            "Expected values: traveler, carrier, weather, policy."
        ),
    )
    severity: str = Field(
        default="",
        description=(
            "The severity level of the travel event, which may determine "
            "which policies are triggered and what approvals are required. "
            "Expected values: low, medium, high."
        ),
    )
    is_reimbursable: bool = Field(
        default=False,
        description=(
            "Whether costs directly associated with this travel event type "
            "are reimbursable under the policy."
        ),
    )
    reimbursement_condition: str = Field(
        default="",
        description=(
            "Any condition that must be satisfied for costs from this event to be "
            "reimbursable. E.g. 'emergency situations only', "
            "'pre-approved by Executive Director'."
        ),
    )
    requires_pre_approval: bool = Field(
        default=False,
        description=(
            "Whether handling or resolving this type of travel event requires "
            "prior written approval from an authorized stakeholder before action is taken."
        ),
    )
    requires_notification: bool = Field(
        default=False,
        description=(
            "Whether the traveler or agent is required to notify the organization "
            "when this event occurs. E.g. hotel cancellation must be communicated "
            "to JRC-DMS staff."
        ),
    )
    documentation_required: bool = Field(
        default=False,
        description=(
            "Whether the traveler must obtain and retain a formal record "
            "as proof of this event. E.g. a cancellation number from a hotel."
        ),
    )


class GeographicScopeEntity(BaseEntitySchema):
    """A geographic context that modifies the applicability or terms of a policy rule.
    Rules may apply differently depending on whether travel is local, national, or international."""

    type: Literal["GeographicScope"] = "GeographicScope"

    scope_name: str = Field(
        default="",
        description=(
            "The canonical name of the geographic scope. "
            "Expected values: Local, Regional, ContinentalUS, NorthAmerica, International."
        ),
    )
    boundary_definition: str = Field(
        default="",
        description=(
            "A plain-language description of what qualifies as within this geographic scope. "
            "E.g. 'Washington DC, Baltimore and surrounding areas', "
            "'within 50 miles each way of the office'."
        ),
    )
    distance_threshold_miles: Optional[float] = Field(
        default=None,
        description=(
            "A numeric distance threshold in miles used to define the boundary "
            "of this scope, if applicable. E.g. 50.0 for a local travel boundary."
        ),
    )
    has_additional_requirements: bool = Field(
        default=False,
        description=(
            "Whether travel within this geographic scope triggers additional "
            "policy requirements not applicable in other scopes. "
            "E.g. mandatory insurance purchase when renting a vehicle internationally."
        ),
    )
    additional_requirements_description: str = Field(
        default="",
        description=(
            "Plain-language description of any additional requirements that are "
            "activated specifically because travel falls within this geographic scope."
        ),
    )

# ============================================================
# GROUP 4: FINANCIAL ENTITIES
# ============================================================


class ExpenseCategoryEntity(BaseEntitySchema):
    """A type of expense that may be incurred during business travel,
    along with its reimbursability status under the policy."""

    type: Literal["ExpenseCategory"] = "ExpenseCategory"

    category_type: str = Field(
        default="",
        description=(
            "The classification of the expense type. Examples: Airfare, Lodging, "
            "Meals, CarRental, Mileage, Parking, Tolls, Baggage, Tips, Internet, "
            "Laundry, Entertainment, CurrencyConversion."
        ),
    )
    reimbursability_status: str = Field(
        default="",
        description=(
            "Whether this expense is reimbursable under the policy. "
            "One of: reimbursable, non-reimbursable, conditional."
        ),
    )
    conditions_for_reimbursement: str = Field(
        default="",
        description=(
            "If reimbursability_status is conditional, the specific conditions "
            "under which this expense qualifies for reimbursement. "
            "Empty string if unconditionally reimbursable or non-reimbursable."
        ),
    )
    applies_to_roles: list[str] = Field(
        default=[],
        description=(
            "The traveler roles for which this expense category is applicable. "
            "Examples: Employee, BoardMember, SiteVisitor, Contractor, Volunteer. "
            "Empty list implies the category applies to all roles."
        ),
    )


class ReimbursementLimitEntity(BaseEntitySchema):
    """A financial cap or rate imposed by a policy rule on a specific
    expense category, defining the maximum amount the organization will cover."""

    type: Literal["ReimbursementLimit"] = "ReimbursementLimit"

    limit_amount: Optional[float] = Field(
        default=None,
        description=(
            "The maximum monetary amount that may be reimbursed. "
            "Null if the limit is expressed as a rate or percentage rather than "
            "a fixed monetary value."
        ),
    )
    currency: str = Field(
        default="USD",
        description=(
            "The currency denomination of the limit amount. Defaults to USD."
        ),
    )
    unit: str = Field(
        default="",
        description=(
            "The unit over which the limit applies. "
            "One of: per_day, per_night, per_trip, per_occurrence, percentage."
        ),
    )
    limit_type: str = Field(
        default="",
        description=(
            "Whether this limit represents a strict ceiling or a soft guideline. "
            "One of: hard_cap, soft_cap, rate."
        ),
    )
    excess_obligation: str = Field(
        default="",
        description=(
            "Who bears financial responsibility for amounts exceeding this limit. "
            "Examples: traveler, organization_with_approval. "
            "Empty string if not specified by the policy."
        ),
    )


class PaymentMethodEntity(BaseEntitySchema):
    """An authorized method by which a travel expense may be paid,
    including any restrictions on its use and associated reporting obligations."""

    type: Literal["PaymentMethod"] = "PaymentMethod"

    method_name: str = Field(
        default="",
        description=(
            "The name of the payment method as referenced in the policy. "
            "Examples: CorporateCreditCard, PersonalCard, DirectBill, CorporateAccount."
        ),
    )
    business_use_only: bool = Field(
        default=False,
        description=(
            "Whether this payment method is strictly restricted to business expenses "
            "and explicitly prohibited for personal use."
        ),
    )
    reporting_required: bool = Field(
        default=False,
        description=(
            "Whether use of this payment method triggers additional reporting "
            "or documentation obligations beyond a standard expense report."
        ),
    )
    violation_consequence: str = Field(
        default="",
        description=(
            "The consequence specified by the policy for misuse of this payment method. "
            "Example: disciplinary_action. "
            "Empty string if no consequence is explicitly stated."
        ),
    )
    statement_submission_required: bool = Field(
        default=False,
        description=(
            "Whether the traveler is required to submit periodic statements "
            "associated with this payment method alongside expense reports."
        ),
    )


class PriorityOrderEntity(BaseEntitySchema):
    """A ranked preference ordering between two or more compliant options
    for transportation modes or accommodation, used to guide least-cost
    and policy-compliant selection."""

    type: Literal["PriorityOrder"] = "PriorityOrder"

    ranked_options: list[str] = Field(
        default=[],
        description=(
            "The available options listed in order of preference from most preferred "
            "to least preferred as defined by the policy. "
            "Examples: ['AirportShuttle', 'HotelVan', 'Taxi', 'CarRental']."
        ),
    )
    preference_basis: str = Field(
        default="",
        description=(
            "The primary basis on which the preference ordering is determined. "
            "One of: cost, practicality, policy."
        ),
    )
    override_allowed: bool = Field(
        default=False,
        description=(
            "Whether a traveler is permitted to deviate from this preference "
            "ordering under approved circumstances."
        ),
    )
    override_condition: str = Field(
        default="",
        description=(
            "The condition under which the priority order may be overridden. "
            "Only populated when override_allowed is true. "
            "Example: prior_approval_from_executive_director."
        ),
    )
    applies_to_mode: str = Field(
        default="",
        description=(
            "The transportation mode or accommodation type this priority ordering "
            "governs. Examples: GroundTransportation, Lodging, AirTravel."
        ),
    )


# ============================================================
# GROUP 5: COMPLIANCE ENTITIES
# ============================================================


class ConstraintEntity(BaseEntitySchema):
    """An input predicate that gates, scopes, or modifies when a PolicyRule applies.
    Constraints are evaluated BEFORE a rule activates to determine whether,
    where, for whom, or under what conditions the rule is relevant.
    Examples: '50 mile minimum for hotel eligibility', '45 day submission window',
    '$200 savings threshold for requiring connecting flights'.
    """

    type: Literal["Constraint"] = "Constraint"

    constraint_type: Optional[str] = Field(
        default=None,
        description=(
            "The category of constraint determining how it gates rule activation. "
            "One of: temporal (time-based windows or deadlines), "
            "quantitative (numeric thresholds on cost, distance, or count), "
            "geographic (location-based scoping), "
            "role_based (applies only to certain traveler roles), "
            "situational (activates on a specific circumstance or event type), "
            "combinatorial (requires multiple constraint types to be satisfied together)."
        ),
    )
    operator: Optional[str] = Field(
        default=None,
        description=(
            "The logical operator used to evaluate the constraint against its value. "
            "One of: greater_than, less_than, equals, within, exceeds, not_equals."
        ),
    )
    value: Optional[str] = Field(
        default=None,
        description=(
            "The threshold or reference value against which the constraint is evaluated. "
            "Always stored as a string regardless of numeric type (e.g. '50', '200', '45', '2'). "
            "Unit of measurement is captured separately in the unit field."
        ),
    )
    unit: Optional[str] = Field(
        default=None,
        description=(
            "The unit of measurement for the constraint value. "
            "One of: miles, USD, days, hours, persons, percentage."
        ),
    )
    reference_point: Optional[str] = Field(
        default=None,
        description=(
            "What the constraint value is measured against or relative to. "
            "Examples: completion_of_travel, requested_departure_time, "
            "one_way_distance, booking_date, per_night, per_day."
        ),
    )


class RequirementEntity(BaseEntitySchema):
    """An output obligation that must be fulfilled once a PolicyRule has been
    determined to apply. Requirements are evaluated AFTER rule activation and
    define what the traveler, stakeholder, or organization must do or produce.
    Examples: 'written approval from Executive Director', 'receipt required above $20',
    'expense report submitted within 45 days', 'must refuel car before return'.
    """

    type: Literal["Requirement"] = "Requirement"

    requirement_type: Optional[str] = Field(
        default=None,
        description=(
            "The category of obligation this requirement imposes. "
            "One of: approval (formal authorization must be obtained), "
            "documentation (a record must be created or submitted), "
            "duty_of_care (an organizational obligation toward the traveler), "
            "notification (a party must be informed of an event or change), "
            "action (a physical or procedural step must be taken)."
        ),
    )
    is_mandatory: Optional[bool] = Field(
        default=None,
        description=(
            "Whether fulfillment of this requirement is strictly mandatory (True) "
            "or recommended but not enforced (False)."
        ),
    )
    deadline: Optional[str] = Field(
        default=None,
        description=(
            "The numeric duration by which this requirement must be fulfilled. "
            "Stored as a string (e.g. '45'). Unit is captured in deadline_unit."
        ),
    )
    deadline_unit: Optional[str] = Field(
        default=None,
        description=(
            "The unit of time for the deadline value. "
            "One of: days, hours, immediately."
        ),
    )
    threshold_amount: Optional[str] = Field(
        default=None,
        description=(
            "A monetary value that triggers this requirement when exceeded. "
            "Stored as a string without currency symbol (e.g. '20.00'). "
            "Relevant primarily for documentation requirements such as receipt thresholds."
        ),
    )
    fulfilled_by: Optional[str] = Field(
        default=None,
        description=(
            "The role, artifact, or action that satisfies this requirement. "
            "For approval requirements: the stakeholder role that must authorize "
            "(e.g. 'ExecutiveDirector', 'ProgramOfficials'). "
            "For documentation requirements: the artifact that must be produced "
            "(e.g. 'Receipt', 'ExpenseReport', 'CancellationNumber', 'MileageLog'). "
            "For action requirements: the party responsible for execution "
            "(e.g. 'Traveler', 'AccountingDepartment')."
        ),
    )
    submission_target: Optional[str] = Field(
        default=None,
        description=(
            "The party or system to which documentation or notification must be submitted. "
            "Examples: AccountingDepartment, JRC-DMS Staff, Hotel, TravelAgent."
        ),
    )


class ConsequenceEntity(BaseEntitySchema):
    """An outcome that results from either compliance with or violation of a PolicyRule.
    Consequences represent the downstream effect the policy imposes on a traveler
    or the organization depending on whether the rule was followed.
    Examples: 'traveler personally liable for no-show charge',
    'disciplinary action for personal use of corporate card',
    'expense reimbursed upon submission of report'.
    """

    type: Literal["Consequence"] = "Consequence"

    consequence_type: Optional[str] = Field(
        default=None,
        description=(
            "The category of outcome this consequence represents. "
            "One of: reimbursement (traveler is compensated for an expense), "
            "personal_liability (traveler bears the cost personally), "
            "disciplinary_action (organizational penalty applied to the traveler), "
            "tax_reporting_obligation (an IRS or tax authority reporting requirement is triggered)."
        ),
    )
    triggered_by: Optional[str] = Field(
        default=None,
        description=(
            "Whether this consequence is triggered by adherence to or breach of the associated rule. "
            "One of: compliance, violation."
        ),
    )
    severity: Optional[str] = Field(
        default=None,
        description=(
            "The relative severity of this consequence, relevant primarily for violation-triggered consequences. "
            "One of: low, medium, high."
        ),
    )
    applies_to_role: Optional[str] = Field(
        default=None,
        description=(
            "The traveler role to whom this consequence applies if it is role-specific. "
            "Leave null if the consequence applies to all traveler roles equally. "
            "Examples: Employee, SiteVisitor, BoardMember."
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
# GROUP 1: POLICY STRUCTURE RELATIONSHIPS
# ============================================================

CONTAINS_POLICY_TO_SECTION = RelationshipSchema(
    type="CONTAINS",
    description=(
        "A Policy document is structurally decomposed into thematic PolicySections. "
        "Each section groups related rules under a common subject area such as Air Travel, "
        "Lodging, or Meals. This is the entry point for navigating the policy hierarchy."
    ),
    valid_source_types=["Policy"],
    valid_target_types=["PolicySection"],
    cardinality="one_to_many",
    is_directed=True,
    mandatory=True,
    inverse_type="PART_OF",
    agent_traversal_hint=(
        "Start here when a travel event occurs. Traverse from Policy down to PolicySection "
        "to identify which thematic area of the policy is relevant before drilling into "
        "specific rules. For example, a flight cancellation event should route the agent "
        "toward the Air Travel section before enumerating applicable PolicyRules."
    ),
)

CONTAINS_SECTION_TO_RULE = RelationshipSchema(
    type="CONTAINS",
    description=(
        "A PolicySection contains one or more discrete, actionable PolicyRules. "
        "This relationship maps thematic sections to their enforceable rules and establishes "
        "the lowest structural level of the policy hierarchy."
    ),
    valid_source_types=["PolicySection"],
    valid_target_types=["PolicyRule"],
    cardinality="one_to_many",
    is_directed=True,
    mandatory=True,
    inverse_type="PART_OF",
    agent_traversal_hint=(
        "Traverse from PolicySection to PolicyRule to enumerate all enforceable rules "
        "within a relevant section. This traversal should always follow a prior "
        "CONTAINS traversal from Policy to PolicySection so that rule evaluation "
        "is already scoped to the correct subject area. Collect all PolicyRule nodes "
        "before applying APPLIES_TO and CONSTRAINED_BY filters."
    ),
)

HAS_EXCEPTION = RelationshipSchema(
    type="HAS_EXCEPTION",
    description=(
        "A PolicyRule has one or more formally defined PolicyExceptions that specify "
        "the conditions under which the standard rule may be overridden, relaxed, or "
        "substituted. An exception does not invalidate the rule — it qualifies it. "
        "Exceptions typically require their own fulfillment obligations such as prior "
        "written approval from an authorized Stakeholder."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["PolicyException"],
    cardinality="one_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="EXCEPTION_OF",
    agent_traversal_hint=(
        "Always traverse from PolicyRule to PolicyException before enforcing or "
        "reporting a rule as binding. If a PolicyException exists, evaluate whether "
        "its qualifying Constraints are satisfied via SATISFIES relationships. "
        "If the exception is active, follow HAS_REQUIREMENT on the PolicyException "
        "node to determine what additional obligations — such as executive approval — "
        "must be fulfilled before the exception can be applied."
    ),
)

GOVERNED_BY = RelationshipSchema(
    type="GOVERNED_BY",
    description=(
        "A PolicyRule traces back to its authoritative source Policy. This relationship "
        "provides provenance for every rule in the graph, enabling version tracking, "
        "audit trails, and cross-policy conflict detection when multiple policies from "
        "different organizations or time periods are active simultaneously within the graph."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["Policy"],
    cardinality="many_to_one",
    is_directed=True,
    mandatory=True,
    inverse_type="CONTAINS",
    agent_traversal_hint=(
        "Traverse from PolicyRule to Policy when provenance must be established — "
        "for example, when verifying that a rule belongs to the correct enterprise "
        "client's active policy version, or when two conflicting PolicyRules have been "
        "retrieved and the agent must determine which policy takes precedence. "
        "Also use this traversal to surface the policy effective date when assessing "
        "whether a rule was in force at the time a travel event occurred."
    ),
)

# ============================================================
# GROUP 2: RULE APPLICABILITY RELATIONSHIPS
# Defines what a rule targets and what scopes its activation.
# These relationships are the primary filter layer for the agent —
# establishing which rules are candidates before constraint
# evaluation (Group 3) and requirement resolution (Group 4).
# ============================================================

APPLIES_TO_ROLE = RelationshipSchema(
    type="APPLIES_TO_ROLE",
    description=(
        "Defines which TravelerRole category a PolicyRule governs. "
        "A rule may apply to one or more roles (e.g. Employee, BoardMember, "
        "SiteVisitor, Contractor, Volunteer). Rules without this relationship "
        "are interpreted as applying to all roles universally."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["TravelerRole"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="ROLE_GOVERNED_BY",
    agent_traversal_hint=(
        "STEP 1 OF RULE FILTERING. When a travel event is received, resolve "
        "the traveler's role first, then traverse APPLIES_TO_ROLE inversely "
        "via ROLE_GOVERNED_BY to retrieve only the PolicyRule nodes relevant "
        "to that role. Discard all rules not connected to the traveler's role "
        "before proceeding to constraint evaluation. Rules with no "
        "APPLIES_TO_ROLE edges are treated as universal and should always "
        "be included in the candidate set."
    ),
)

APPLIES_TO_EXPENSE = RelationshipSchema(
    type="APPLIES_TO_EXPENSE",
    description=(
        "Associates a PolicyRule with the ExpenseCategory it governs. "
        "Establishes which rules are relevant when an expense of a given "
        "type is incurred during business travel. A single rule may govern "
        "multiple expense categories, and a single expense category may be "
        "governed by multiple rules simultaneously."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["ExpenseCategory"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="EXPENSE_GOVERNED_BY",
    agent_traversal_hint=(
        "When a travel event triggers or modifies an expense, identify the "
        "ExpenseCategory of that expense and traverse EXPENSE_GOVERNED_BY "
        "to retrieve all governing PolicyRule nodes. This is the primary "
        "entry point for expense reimbursability decisions. Combine the "
        "resulting rule set with the role-filtered set from APPLIES_TO_ROLE "
        "using intersection to narrow to rules that are both role-relevant "
        "and expense-relevant before evaluating LIMITS and COVERS."
    ),
)

APPLIES_TO_MODE = RelationshipSchema(
    type="APPLIES_TO_MODE",
    description=(
        "Associates a PolicyRule with the TransportationMode it governs. "
        "Defines which rules become active when a specific mode of transport "
        "is selected, disrupted, or proposed as an alternative. A rule may "
        "govern multiple modes, and a mode may be subject to multiple rules."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["TransportationMode"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="MODE_GOVERNED_BY",
    agent_traversal_hint=(
        "When a travel event involves a change to or selection of a "
        "transportation mode — such as a flight cancellation requiring "
        "ground transport, or a rebooking requiring a car rental — traverse "
        "MODE_GOVERNED_BY from the proposed TransportationMode node to "
        "retrieve all governing PolicyRule nodes. This is critical for "
        "cascading disruption scenarios: when CASCADES_TO produces a new "
        "TravelEvent requiring a mode change, this relationship determines "
        "the full policy constraint set for the replacement mode. Use "
        "PREFERRED_OVER (Group 9) in conjunction to select the most "
        "policy-compliant alternative mode."
    ),
)

APPLIES_IN_CONTEXT = RelationshipSchema(
    type="APPLIES_IN_CONTEXT",
    description=(
        "Associates a PolicyRule with the BusinessContext in which it is "
        "active. BusinessContext represents the purpose of the travel — "
        "such as BoardMeeting, SiteVisit, or Exhibit. Rules connected via "
        "this relationship are only applicable when the traveler is operating "
        "within the specified context. Rules without this relationship apply "
        "across all business contexts."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["BusinessContext"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="CONTEXT_GOVERNED_BY",
    agent_traversal_hint=(
        "Business context must be established at the start of any policy "
        "resolution session and held constant throughout. Traverse "
        "CONTEXT_GOVERNED_BY from the active BusinessContext node to retrieve "
        "context-specific PolicyRule candidates. Rules retrieved here should "
        "be unioned with universal rules (those with no APPLIES_IN_CONTEXT "
        "edges) and then intersected against the role-filtered and "
        "expense-filtered sets. This is especially important in disruption "
        "scenarios where two rule sets may conflict — for example, a "
        "SiteVisit context triggers car rental pre-approval requirements "
        "that do not apply in a BoardMeeting context."
    ),
)

CONSTRAINED_BY = RelationshipSchema(
    type="CONSTRAINED_BY",
    description=(
        "Associates a PolicyRule with a Constraint that gates or modifies "
        "its activation. A constraint defines the conditions under which a "
        "rule is active — including temporal windows, quantitative thresholds, "
        "geographic boundaries, role-based conditions, and situational "
        "predicates. This is the unified replacement for the previously "
        "separate HAS_TIME_CONSTRAINT, HAS_THRESHOLD, APPLIES_IN_SCOPE, "
        "and CONSTRAINED_BY relationships. A rule may have multiple "
        "Constraint nodes, all of which must be satisfied for the rule to "
        "be considered active. Constraints are evaluated after role, expense, "
        "mode, and context filtering has reduced the candidate rule set."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["Constraint"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="CONSTRAINS",
    agent_traversal_hint=(
        "FINAL GATE IN RULE FILTERING. After role, expense, mode, and context "
        "filtering has produced a candidate PolicyRule set, traverse "
        "CONSTRAINED_BY for each candidate rule and evaluate all associated "
        "Constraint nodes against the current travel event's parameters "
        "(expense amount, distance, trip duration, geographic location, "
        "traveler count, situational flags). A rule is only considered active "
        "if ALL of its constraints evaluate to true. Rules with no "
        "CONSTRAINED_BY edges are unconditionally active within their "
        "applicability scope. After a rule is confirmed active, traverse "
        "outward from its Constraint nodes via SCOPES (Group 3) to determine "
        "which Requirements are additionally activated by those same "
        "constraints — this prevents missed obligations such as receipt "
        "thresholds or approval triggers."
    ),
)

# ============================================================
# GROUP 3: CONSTRAINT LOGIC
# Describes how Constraint nodes relate to Requirement and
# PolicyException nodes. These relationships make conditional
# obligation logic explicitly traversable in the graph rather
# than buried in rule text or node properties.
# ============================================================

SCOPES = RelationshipSchema(
    type="SCOPES",
    description=(
        "A Constraint node determines the qualifying conditions under which a "
        "Requirement is activated. This makes threshold- and situation-driven "
        "obligation logic an explicit graph traversal rather than an implicit "
        "property lookup. For example, a QUANTITATIVE Constraint "
        "(expense > $20) scopes a DOCUMENTATION Requirement (receipt must be "
        "submitted), meaning the requirement is only active when the constraint "
        "condition is met. A single Constraint may scope multiple Requirements, "
        "and a single Requirement may be scoped by multiple Constraints where "
        "all conditions must hold simultaneously."
    ),
    valid_source_types=["Constraint"],
    valid_target_types=["Requirement"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="SCOPED_BY",
    agent_traversal_hint=(
        "Traverse SCOPES when determining whether a Requirement is currently "
        "active given the runtime state of a travel event or expense. Starting "
        "from a candidate Requirement node, follow SCOPED_BY edges to retrieve "
        "all associated Constraint nodes and evaluate each constraint condition "
        "against the current context — e.g. expense amount, trip duration, "
        "traveler role, or geographic scope. If all linked Constraint conditions "
        "are satisfied, the Requirement is active and must be fulfilled. If any "
        "Constraint condition is not met, the Requirement is not triggered. "
        "This traversal is essential for autonomous compliance checking without "
        "requiring a human agent to interpret rule text."
    ),
)

SATISFIES = RelationshipSchema(
    type="SATISFIES",
    description=(
        "A Constraint node defines the qualifying condition that must be true "
        "for a PolicyException to be considered valid and applicable. This "
        "makes exception eligibility logic explicitly traversable rather than "
        "encoded in free text. For example, a SITUATIONAL Constraint "
        "(free upgrade provided by carrier) satisfies a PolicyException "
        "(business class travel permitted), meaning the exception is only "
        "valid when that specific condition holds. A PolicyException may "
        "require multiple Constraint conditions to all be satisfied "
        "simultaneously before the exception can be invoked."
    ),
    valid_source_types=["Constraint"],
    valid_target_types=["PolicyException"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="SATISFIED_BY",
    agent_traversal_hint=(
        "Traverse SATISFIES when an agent needs to determine whether a "
        "PolicyException can be legitimately applied to the current situation. "
        "Starting from a candidate PolicyException node, follow SATISFIED_BY "
        "edges to retrieve all Constraint nodes whose conditions must hold. "
        "Evaluate each Constraint against the runtime context of the travel "
        "event. Only if all linked Constraints are satisfied should the "
        "exception be considered valid and the associated PolicyRule overridden. "
        "This traversal prevents invalid exception invocation and ensures the "
        "agent applies exceptions only under their intended qualifying "
        "circumstances."
    ),
)

# ============================================================
# RELATIONSHIP SCHEMA REGISTRY
# Group 4: Requirement & Fulfillment
# ============================================================

HAS_REQUIREMENT = RelationshipSchema(
    type="HAS_REQUIREMENT",
    description=(
        "Expresses that a source entity imposes an obligation that must be fulfilled. "
        "Unified replacement for REQUIRES_APPROVAL, REQUIRES_DOCUMENTATION, "
        "EXCEPTION_REQUIRES, and CREATES_OBLIGATION. The nature of the obligation "
        "is discriminated by the Requirement.requirement_type property "
        "(APPROVAL | DOCUMENTATION | DUTY_OF_CARE | NOTIFICATION | ACTION) "
        "rather than by separate relationship types, allowing a single traversal "
        "path to surface all obligations regardless of their class."
    ),
    valid_source_types=["PolicyRule", "PolicyException", "ExpenseCategory"],
    valid_target_types=["Requirement"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="REQUIRED_BY",
    agent_traversal_hint=(
        "Traverse from any activated PolicyRule or PolicyException to surface all "
        "obligations that must be satisfied before or after the rule is applied. "
        "Filter target Requirement nodes by requirement_type to isolate the specific "
        "class of obligation relevant to the current decision context. "
        "Always check Requirement.is_mandatory to distinguish strict obligations "
        "from discretionary ones before determining whether the agent must block "
        "on fulfillment or may proceed. When source is a PolicyException, "
        "the retrieved Requirement represents the condition that must be met "
        "for the exception itself to be valid — treat it as a gate, not a "
        "post-condition. When source is an ExpenseCategory, the retrieved "
        "Requirement represents an inherent obligation attached to that expense "
        "type regardless of which rule triggered it."
    ),
)

FULFILLED_BY = RelationshipSchema(
    type="FULFILLED_BY",
    description=(
        "Identifies the party responsible for satisfying a Requirement. "
        "Unified replacement for APPROVAL_GRANTED_BY and DOCUMENTATION_SUBMITTED_TO. "
        "The target may be an internal Stakeholder (e.g. Executive Director, "
        "Accounting Department) where organizational action is needed, or a "
        "TravelerRole where the traveler themselves must act to satisfy the "
        "obligation. A single Requirement may have multiple fulfilling parties "
        "where sequential or joint fulfillment is required."
    ),
    valid_source_types=["Requirement"],
    valid_target_types=["Stakeholder", "TravelerRole"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="FULFILLS",
    agent_traversal_hint=(
        "Traverse from an active Requirement to determine who must act to satisfy it. "
        "When the target is a Stakeholder, route the obligation to that party for "
        "authorization or processing — this is a hard dependency and the agent "
        "must not proceed past this requirement without confirmation of fulfillment. "
        "When the target is a TravelerRole, the agent must surface the obligation "
        "as an instruction or notification to the traveler directly. "
        "When multiple FULFILLED_BY edges exist on a single Requirement node, "
        "inspect Requirement.fulfillment_order to determine whether fulfillment "
        "is sequential (one party must act before another) or joint "
        "(all parties must act). Use in combination with the SCOPES relationship "
        "from Group 3 to first verify that the governing Constraint condition "
        "is met before treating the Requirement as active and routing it "
        "to the fulfilling party."
    ),
)

# ── GROUP 5: FINANCIAL RELATIONSHIPS ────────────────────────────────────────

LIMITS = RelationshipSchema(
    type="LIMITS",
    description=(
        "A PolicyRule imposes a financial cap, rate, or ceiling expressed "
        "as a ReimbursementLimit node. Defines the maximum allowable spend "
        "for an expense category within a given policy context. A single "
        "rule may carry multiple ReimbursementLimit nodes where different "
        "caps apply under different conditions."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["ReimbursementLimit"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="LIMITED_BY",
    agent_traversal_hint=(
        "Traverse from a PolicyRule to its ReimbursementLimit nodes before "
        "authorizing or rebooking an expense. Compare the proposed expense "
        "amount against the limit_amount and unit properties on the "
        "ReimbursementLimit node to determine compliance. Where multiple "
        "ReimbursementLimit nodes exist on a single PolicyRule, evaluate "
        "each in conjunction with its CONSTRAINED_BY edges to select the "
        "limit that is active under the current traveler role, geographic "
        "scope, and business context before rendering a decision."
    ),
)

COVERS = RelationshipSchema(
    type="COVERS",
    description=(
        "A PolicyRule explicitly authorizes reimbursement of an "
        "ExpenseCategory. Represents a positive reimbursability declaration "
        "for a class of expenses under the conditions scoped by the rule. "
        "Must always be evaluated after PROHIBITS edges have been checked "
        "on the same ExpenseCategory — a PROHIBITS relationship takes "
        "precedence over COVERS regardless of rule ordering."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["ExpenseCategory"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="COVERED_BY",
    agent_traversal_hint=(
        "Traverse from an ExpenseCategory back via COVERED_BY to identify "
        "which PolicyRules authorize its reimbursement. Always resolve "
        "PROHIBITS edges first — if any active rule prohibits the expense "
        "category under the current context, COVERS edges are superseded "
        "and should not be used to approve the claim. Once no PROHIBITS "
        "edges block the expense, confirm the covering PolicyRule is active "
        "for the current TravelerRole via APPLIES_TO_ROLE and for the "
        "current BusinessContext via APPLIES_IN_CONTEXT before approving "
        "the reimbursement. Then traverse LIMITS to apply any financial cap."
    ),
)

PROHIBITS = RelationshipSchema(
    type="PROHIBITS",
    description=(
        "A PolicyRule explicitly disallows reimbursement of an "
        "ExpenseCategory. Represents a hard exclusion of a class of "
        "expenses from reimbursability. Acts as a policy stop condition — "
        "a matched PROHIBITS edge must be resolved before any COVERS edge "
        "on the same ExpenseCategory is considered."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["ExpenseCategory"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="PROHIBITED_BY",
    agent_traversal_hint=(
        "Traverse from an ExpenseCategory via PROHIBITED_BY as the first "
        "step in any reimbursement evaluation. A matched PROHIBITS edge "
        "constitutes a hard stop — the expense is non-reimbursable "
        "regardless of any COVERS relationships present on the same "
        "ExpenseCategory. Confirm the prohibiting PolicyRule is active for "
        "the current TravelerRole and BusinessContext before applying the "
        "stop. If active, surface the prohibition to the traveler prior to "
        "submission to prevent non-compliant claims from entering the "
        "reimbursement pipeline. Do not proceed to COVERS evaluation until "
        "all PROHIBITS edges have been cleared."
    ),
)

PAID_THROUGH = RelationshipSchema(
    type="PAID_THROUGH",
    description=(
        "An ExpenseCategory has one or more authorized PaymentMethods "
        "through which it must or may be settled. Defines the valid payment "
        "instruments for a class of expenses. Where a corporate payment "
        "method is designated, use of a personal payment instrument "
        "constitutes a policy violation subject to consequence."
    ),
    valid_source_types=["ExpenseCategory"],
    valid_target_types=["PaymentMethod"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="AUTHORIZED_FOR",
    agent_traversal_hint=(
        "Traverse from an ExpenseCategory to its PaymentMethod nodes to "
        "validate that the correct payment instrument is being used before "
        "logging or authorizing an expense. Inspect the allowed_for and "
        "reporting_required properties on the PaymentMethod node — if "
        "allowed_for is set to business_only and a personal instrument was "
        "used, flag as a policy violation and route to the responsible "
        "Stakeholder via the PolicyRule ENFORCED_BY edge for review. "
        "Where reporting_required is true on the PaymentMethod node, "
        "trigger the associated DocumentationRequirement via HAS_REQUIREMENT "
        "to ensure the correct audit trail is initiated."
    ),
)

# ============================================================
# GROUP 6: TRAVEL EVENT RELATIONSHIPS
# ============================================================

TRIGGERS = RelationshipSchema(
    type="TRIGGERS",
    description=(
        "A travel event activates one or more policy rules that must be "
        "evaluated and potentially enforced. Represents the primary entry "
        "point from a real-world disruption into the policy graph. A single "
        "event may trigger multiple rules across different policy sections "
        "simultaneously — e.g. a flight cancellation triggers both a "
        "rebooking rule and a lodging rule."
    ),
    valid_source_types=["TravelEvent"],
    valid_target_types=["PolicyRule"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="TRIGGERED_BY",
    agent_traversal_hint=(
        "Entry point for agentic policy resolution. When a TravelEvent is "
        "instantiated, immediately traverse all TRIGGERS edges to surface the "
        "full set of activated PolicyRules. Each retrieved PolicyRule should "
        "then seed parallel traversals into APPLIES_TO_ROLE, CONSTRAINED_BY, "
        "HAS_REQUIREMENT, and LIMITS to determine applicability, obligations, "
        "and financial constraints for the specific traveler and context."
    ),
)

TRIGGERS_REQUIREMENT = RelationshipSchema(
    type="TRIGGERS_REQUIREMENT",
    description=(
        "A travel event directly activates a requirement without passing "
        "through a policy rule. Used specifically for duty of care obligations "
        "and immediate action requirements that arise from the event itself "
        "rather than from a governing rule — e.g. an emergency medical event "
        "activates a duty of care requirement regardless of whether a matching "
        "policy rule exists. Unified replacement for ACTIVATES_DUTY_OF_CARE."
    ),
    valid_source_types=["TravelEvent"],
    valid_target_types=["Requirement"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="REQUIREMENT_TRIGGERED_BY",
    agent_traversal_hint=(
        "Traverse in parallel with TRIGGERS on every TravelEvent. While "
        "TRIGGERS surfaces rule-mediated obligations, this relationship "
        "surfaces obligations that are unconditional and immediate. "
        "Prioritize DUTY_OF_CARE type Requirements retrieved here above "
        "all other resolution paths. Traverse FULFILLED_BY on each "
        "retrieved Requirement to identify which Stakeholder must act "
        "and within what timeframe."
    ),
)

CASCADES_TO = RelationshipSchema(
    type="CASCADES_TO",
    description=(
        "One travel disruption event causes a downstream travel event, "
        "forming a directed chain of effects. Captures the real-world "
        "dependency between disruptions — e.g. a missed connection cascades "
        "to an unplanned overnight stay, which cascades to an unplanned meal "
        "expense. Enables the agent to reason about the full impact surface "
        "of an initial disruption rather than treating each event in "
        "isolation."
    ),
    valid_source_types=["TravelEvent"],
    valid_target_types=["TravelEvent"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="CASCADED_FROM",
    agent_traversal_hint=(
        "Perform a recursive depth-first traversal from the initial "
        "TravelEvent across all CASCADES_TO edges to construct the full "
        "downstream event chain before beginning policy resolution. "
        "Each node in the resulting chain should independently seed "
        "TRIGGERS and TRIGGERS_REQUIREMENT traversals so that the agent "
        "resolves policy implications for the entire disruption surface "
        "simultaneously rather than reactively event by event. Cycle "
        "detection is required — guard against circular cascade paths."
    ),
)

AFFECTS = RelationshipSchema(
    type="AFFECTS",
    description=(
        "A travel event has direct financial or logistical implications for "
        "an expense category, potentially changing reimbursability status, "
        "triggering new expense eligibility, or exposing the traveler to "
        "out-of-pocket costs. Bridges the event layer to the financial layer "
        "of the graph — e.g. a flight cancellation affects the Airfare "
        "expense category by introducing rebooking fees and potentially "
        "affects Lodging by creating an unplanned overnight need."
    ),
    valid_source_types=["TravelEvent"],
    valid_target_types=["ExpenseCategory"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="AFFECTED_BY",
    agent_traversal_hint=(
        "Traverse from a TravelEvent across AFFECTS edges to identify all "
        "expense categories that carry financial implications. For each "
        "retrieved ExpenseCategory, continue traversal along COVERS and "
        "PROHIBITS from PolicyRule and LIMITS to ReimbursementLimit to "
        "determine whether the newly incurred expense is reimbursable, "
        "capped, or disallowed. Surface the delta between expected and "
        "actual expense exposure to the traveler and travel manager."
    ),
)

REQUIRES_ACTION_FROM = RelationshipSchema(
    type="REQUIRES_ACTION_FROM",
    description=(
        "A travel event mandates that a specific stakeholder take a defined "
        "action. Used to drive notification, escalation, and coordination "
        "workflows when a disruption occurs. A single event may require "
        "action from multiple stakeholders simultaneously — e.g. a hotel "
        "no-show requires the traveler to retain a cancellation number, "
        "the travel agent to rebook, and the accounting department to "
        "process any resulting charges."
    ),
    valid_source_types=["TravelEvent"],
    valid_target_types=["Stakeholder"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="ACTION_REQUIRED_BY",
    agent_traversal_hint=(
        "Traverse immediately upon TravelEvent instantiation to identify "
        "all Stakeholders who must be notified or who must act. Use the "
        "retrieved Stakeholder nodes to seed automated notification and "
        "task assignment workflows. Cross-reference with REQUIRES_APPROVAL "
        "traversals on triggered PolicyRules to determine whether any of "
        "the required-action Stakeholders are also approval authorities — "
        "consolidating contact points where possible to reduce coordination "
        "overhead."
    ),
)

RESOLVED_BY = RelationshipSchema(
    type="RESOLVED_BY",
    description=(
        "A travel event has one or more policy rules that define the approved "
        "resolution path. Distinguishes the rule that governs how to respond "
        "to an event from rules that are merely triggered by it. While "
        "TRIGGERS surfaces all rules activated by an event, RESOLVED_BY "
        "identifies the specific rule that prescribes the correct corrective "
        "action — e.g. a rebooking event is triggered by a cancellation but "
        "resolved by the rebooking fee reimbursement rule."
    ),
    valid_source_types=["TravelEvent"],
    valid_target_types=["PolicyRule"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="RESOLVES",
    agent_traversal_hint=(
        "Traverse after TRIGGERS to narrow the full set of activated "
        "PolicyRules down to those that prescribe resolution actions. "
        "Where multiple RESOLVED_BY edges exist for a single TravelEvent, "
        "traverse HAS_PRIORITY_ORDER and SUPERSEDES on the retrieved "
        "PolicyRules to rank resolution paths. Then traverse each resolution "
        "rule's HAS_REQUIREMENT, LIMITS, and CONSTRAINED_BY edges to "
        "assemble a complete, ordered action plan with associated financial "
        "constraints and approval requirements."
    ),
)

# ============================================================
# GROUP 7: STAKEHOLDER RESPONSIBILITY RELATIONSHIPS


ENFORCED_BY = RelationshipSchema(
    type="ENFORCED_BY",
    description=(
        "A policy rule is monitored and enforced by a specific stakeholder or "
        "department. Defines the accountability chain for ensuring a rule is "
        "followed and identifies who must be notified when a violation is detected "
        "or a non-compliant expense submission is received."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["Stakeholder"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="ENFORCES",
    agent_traversal_hint=(
        "Traverse when a potential policy violation is detected or a non-compliant "
        "expense is submitted. Use the result to identify which stakeholder must be "
        "notified before proceeding and to construct the appropriate escalation path."
    ),
)


MANAGED_BY = RelationshipSchema(
    type="MANAGED_BY",
    description=(
        "A business travel context has a designated stakeholder responsible for "
        "coordinating logistics, accommodations, and travel arrangements specific "
        "to that context. Identifies the authoritative point of contact for "
        "context-scoped travel decisions and pre-approvals."
    ),
    valid_source_types=["BusinessContext"],
    valid_target_types=["Stakeholder"],
    cardinality="many_to_one",
    is_directed=True,
    mandatory=False,
    inverse_type="MANAGES",
    agent_traversal_hint=(
        "Traverse when a TravelEvent occurs within a specific BusinessContext "
        "(e.g., SiteVisit, BoardMeeting) to identify the responsible coordinator "
        "who must be notified, holds pre-approval authority for that context, "
        "or is accountable for resolving the disruption."
    ),
)


RESPONSIBLE_FOR_TRAVELER_ROLE = RelationshipSchema(
    type="RESPONSIBLE_FOR",
    description=(
        "A stakeholder holds organizational duty of care and oversight "
        "responsibility toward a category of traveler. Defines who is accountable "
        "for the welfare, policy compliance, and reimbursement processing of a "
        "given traveler role throughout the duration of a trip."
    ),
    valid_source_types=["Stakeholder"],
    valid_target_types=["TravelerRole"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="HAS_RESPONSIBLE_STAKEHOLDER",
    agent_traversal_hint=(
        "Traverse when a traveler in a specific role experiences a disruption, "
        "submits an expense, or requires assistance. Use the result to identify "
        "which stakeholder holds active duty of care obligations and reimbursement "
        "authority toward that traveler at that moment."
    ),
)


RESPONSIBLE_FOR_POLICY_SECTION = RelationshipSchema(
    type="RESPONSIBLE_FOR",
    description=(
        "A stakeholder owns and maintains a specific section of the corporate "
        "travel policy. Defines who is the authoritative interpreter of that "
        "section, who can grant contextual exceptions within its scope, and "
        "who is responsible for keeping it current."
    ),
    valid_source_types=["Stakeholder"],
    valid_target_types=["PolicySection"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="OWNED_BY",
    agent_traversal_hint=(
        "Traverse when a policy interpretation question or compliance dispute "
        "arises within a specific section. Use the result to surface the "
        "authoritative stakeholder who can provide a ruling, clarify intent, "
        "or grant a contextual exception within that section."
    ),
)


AUTHORIZED_TO_APPROVE = RelationshipSchema(
    type="AUTHORIZED_TO_APPROVE",
    description=(
        "A stakeholder holds the organizational authority to grant written "
        "approval for a defined policy exception. Establishes the authorization "
        "chain that must be satisfied before a non-compliant action can be "
        "taken, booked, or submitted for reimbursement."
    ),
    valid_source_types=["Stakeholder"],
    valid_target_types=["PolicyException"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="REQUIRES_AUTHORIZATION_FROM",
    agent_traversal_hint=(
        "Traverse when a traveler or agent needs to proceed with a non-standard "
        "action flagged against a PolicyRule. Use the result to determine which "
        "stakeholder must provide written approval before the action is taken or "
        "the associated expense is submitted. If that stakeholder is unavailable, "
        "continue traversal via REPORTS_TO to find the escalation path."
    ),
)


REPORTS_TO = RelationshipSchema(
    type="REPORTS_TO",
    description=(
        "Defines the organizational reporting hierarchy between two stakeholders. "
        "Establishes the escalation chain used when an approval, compliance "
        "decision, or exception authorization cannot be resolved at the "
        "immediate stakeholder level due to unavailability or insufficient "
        "authority."
    ),
    valid_source_types=["Stakeholder"],
    valid_target_types=["Stakeholder"],
    cardinality="many_to_one",
    is_directed=True,
    mandatory=False,
    inverse_type="HAS_DIRECT_REPORT",
    agent_traversal_hint=(
        "Traverse when the immediately responsible stakeholder identified via "
        "ENFORCED_BY, AUTHORIZED_TO_APPROVE, or RESPONSIBLE_FOR is unavailable "
        "or lacks sufficient authority to resolve the current decision. Traverse "
        "iteratively up the chain until a stakeholder with sufficient authority "
        "is reached."
    ),
)


MANDATES_USE_OF = RelationshipSchema(
    type="MANDATES_USE_OF",
    description=(
        "A policy rule requires travelers to use a specific external service "
        "provider or vendor for a given travel need. Deviation from a mandated "
        "provider may result in non-reimbursement of the expense or require "
        "explicit exception approval prior to booking."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["ServiceProvider"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="MANDATED_BY",
    agent_traversal_hint=(
        "Traverse when booking or arranging any travel component to verify that "
        "the selected vendor matches the policy-mandated provider for the relevant "
        "PolicyRule. If a mismatch is detected, flag as a compliance risk and "
        "surface the AUTHORIZED_TO_APPROVE path to determine whether an exception "
        "can be granted before confirming the booking."
    ),
)

# ============================================================
# GROUP 8: COMPLIANCE & CONSEQUENCE
# Outcomes resulting from adherence to or violation of policy.
# ============================================================

RESULTS_IN = RelationshipSchema(
    type="RESULTS_IN",
    description=(
        "A node produces a defined outcome as a result of its activation, compliance "
        "state, or occurrence. When sourced from a PolicyRule, captures the outcome of "
        "adherence (e.g. reimbursement approval) or violation (e.g. disciplinary action, "
        "personal liability). When sourced from a TravelEvent, captures direct consequences "
        "of a disruption independent of an explicit rule — such as a no-show charge or "
        "personal financial liability incurred when cancellation procedure was not followed."
    ),
    valid_source_types=["PolicyRule", "TravelEvent"],
    valid_target_types=["Consequence"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="PRODUCED_BY",
    agent_traversal_hint=(
        "Traverse from PolicyRule or TravelEvent to Consequence before committing to any "
        "action path. Branch on Consequence.consequence_type: REIMBURSEMENT paths confirm "
        "eligible cost recovery for the traveler; PERSONAL_LIABILITY paths signal that the "
        "traveler bears the cost; DISCIPLINARY_ACTION paths signal organizational risk; "
        "TAX_REPORTING_OBLIGATION paths signal IRS documentation requirements. Always "
        "traverse this relationship during disruption resolution to ensure all downstream "
        "outcomes are surfaced and weighed before a resolution is selected."
    )
)

PRODUCED_BY = RelationshipSchema(
    type="PRODUCED_BY",
    description=(
        "Inverse of RESULTS_IN. A Consequence is produced by a PolicyRule or TravelEvent. "
        "Enables backward traversal from a known or observed consequence to identify all "
        "rules or events capable of generating it. Primarily used for root cause analysis, "
        "audit trails, and identifying which policy rules are implicated in a given outcome."
    ),
    valid_source_types=["Consequence"],
    valid_target_types=["PolicyRule", "TravelEvent"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="RESULTS_IN",
    agent_traversal_hint=(
        "Traverse from a Consequence node backward to its source PolicyRule or TravelEvent "
        "when performing post-travel compliance auditing or expense dispute resolution. "
        "Use to answer: 'What rule or event is responsible for this outcome?' Particularly "
        "useful when a traveler disputes a non-reimbursement decision — traverse to the "
        "originating PolicyRule and surface its CONSTRAINED_BY and APPLIES_TO_ROLE "
        "relationships to validate whether the rule was correctly applied."
    )
)

# ============================================================
# GROUP 9: PRIORITY & PREFERENCE RELATIONSHIPS
# ============================================================

HAS_PRIORITY_ORDER = RelationshipSchema(
    type="HAS_PRIORITY_ORDER",
    description=(
        "Links a PolicyRule to a PriorityOrder node that encodes a fully "
        "ranked sequence of acceptable options for satisfying that rule. "
        "Used when a rule permits multiple options but mandates a strict "
        "preference sequence. The PriorityOrder node acts as a hub — all "
        "ranked candidates connect to it via RANKED_IN edges carrying an "
        "integer rank property. A PolicyRule may have at most one "
        "PriorityOrder node. Replaces the need for pairwise PREFERRED_OVER "
        "edges entirely."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["PriorityOrder"],
    cardinality="one_to_one",
    is_directed=True,
    mandatory=False,
    inverse_type=None,
    agent_traversal_hint=(
        "When a triggered PolicyRule permits multiple options, traverse "
        "HAS_PRIORITY_ORDER to the PriorityOrder hub node, then traverse "
        "all incoming RANKED_IN edges sorted ascending by rank. Validate "
        "each candidate in rank order against all active Constraint nodes "
        "and ReimbursementLimits. Select the first candidate that satisfies "
        "all constraints. If no candidate is valid, traverse "
        "HAS_REQUIREMENT on the PolicyRule to determine whether an approval "
        "Requirement must be fulfilled before acting outside the ranked set."
    ),
)

RANKED_IN = RelationshipSchema(
    type="RANKED_IN",
    description=(
        "Registers an entity as a ranked member of a PriorityOrder. The "
        "integer rank property on this edge defines the entity's position "
        "in the ordering — rank 1 is highest priority. Valid source types "
        "include any entity that can be a selectable option under a policy "
        "rule: TransportationMode, Accommodation, ClassOfService, or "
        "ServiceProvider. Multiple entities of different types may "
        "participate in the same PriorityOrder, allowing mixed-type "
        "rankings where policy requires it."
    ),
    valid_source_types=[
        "TransportationMode",
        "Accommodation",
        "ClassOfService",
        "ServiceProvider",
    ],
    valid_target_types=["PriorityOrder"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="PRIORITY_ORDER_CONTAINS",
    agent_traversal_hint=(
        "Do not traverse RANKED_IN directly in isolation. Always approach "
        "via the PriorityOrder hub — start from PolicyRule, traverse "
        "HAS_PRIORITY_ORDER to PriorityOrder, then retrieve all RANKED_IN "
        "edges sorted by ascending rank value. The rank property on each "
        "edge is the sole source of ordering truth — do not infer order "
        "from graph topology or node properties."
    ),
)

SUPERSEDES = RelationshipSchema(
    type="SUPERSEDES",
    description=(
        "Indicates that one PolicyRule takes precedence over another when "
        "both are simultaneously activated by the same TravelEvent or "
        "BusinessContext. Encodes explicit conflict resolution logic between "
        "rules so that competing obligations or limits can be resolved "
        "deterministically without human intervention. The source rule "
        "overrides the target rule. Precedence may itself be conditional — "
        "any Constraint node attached to the source rule via CONSTRAINED_BY "
        "defines the scope within which the override applies."
    ),
    valid_source_types=["PolicyRule"],
    valid_target_types=["PolicyRule"],
    cardinality="many_to_many",
    is_directed=True,
    mandatory=False,
    inverse_type="SUPERSEDED_BY",
    agent_traversal_hint=(
        "When multiple PolicyRules are triggered by the same TravelEvent "
        "and produce conflicting obligations, limits, or ranked options, "
        "traverse SUPERSEDES edges among the activated rules to establish "
        "a precedence order before resolving the required action. Check "
        "CONSTRAINED_BY edges on the superseding rule first — if those "
        "Constraints are not satisfied by the current context the override "
        "does not apply and the conflict must be escalated via "
        "REQUIRES_ACTION_FROM to the appropriate Stakeholder."
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
            lines.append("  Typed attributes:")
            for field_name, field_info in typed_fields.items():
                type_str = _python_type_to_json_type(field_info.annotation)
                desc = field_info.description or ""
                required = field_info.is_required()
                req_str = " (required)" if required else ""
                lines.append(
                    f"    - {field_name} ({type_str}{req_str}): {desc}"
                )

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
    lines = [
        "Create each entity with the following fields:\n",
        "**id** (required)",
        f"- Format: Start with the prefix `{id_prefix}_` followed by a "
        "descriptive identifier",
        "- Use lowercase with underscores",
        "- Make it descriptive of the entity content",
        f"- Example: `{id_prefix}_role_stakeholders` or "
        f"`{id_prefix}_doc_policy`\n",
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
            "- If a value is not present in the source text, leave the "
            "field as an empty string or empty list."
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
            if "array" in type_str:
                val = "[]"
            elif type_str in ("integer", "number"):
                val = '""'
            else:
                val = '""'
            comma = "," if i < len(typed_fields) - 1 else ","
            lines.append(f'      "{field_name}": {val}{comma}')
    else:
        lines.append('      "attributes": {},')

    lines.append('      "source_anchor": {')
    lines.append('        "source_text": "Exact verbatim quote",')
    lines.append('        "source_section": "1"')
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

    for rs in RELATIONSHIP_SCHEMAS:
        source_str = (
            ", ".join(rs.valid_source_types)
            if rs.valid_source_types
            else "any"
        )
        target_str = (
            ", ".join(rs.valid_target_types)
            if rs.valid_target_types
            else "any"
        )
        lines.append(f"- **{rs.type}**: {rs.description}")
        lines.append(f"  Source: [{source_str}] → Target: [{target_str}]")
        lines.append("")

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
