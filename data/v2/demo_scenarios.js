const scenarios = [
  {
    "id": "earthquake_l3",
    "name": "⚡ Level 3 Earthquake — Full Response Chain",
    "desc": "8-step traversal: severity classification → service activation → alert cascade → welfare check → authorization → escalation",
    "severity": "high",
    "sevLabel": "Level 3 — Action Required",
    "incidentLabel": "6.1 Magnitude Earthquake — Tokyo, Japan",
    "actions": [
      {
        "name": "Traveler Alert (SMS)",
        "time": "< 60 min (SLO)",
        "who": "Direct Travel"
      },
      {
        "name": "Welfare Check Outreach",
        "time": "3 attempts / 2 channels / 90 min",
        "who": "Direct Travel"
      },
      {
        "name": "Live Voice Contact",
        "time": "< 15 min after NEED ASSISTANCE",
        "who": "Direct Travel"
      },
      {
        "name": "Client Escalation",
        "time": "< 60 min",
        "who": "Primary Program Owner"
      },
      {
        "name": "Incident Response Activation",
        "time": "Immediate upon auth",
        "who": "Direct Travel + Client"
      },
      {
        "name": "Specialist Provider Coordination",
        "time": "Upon Client auth",
        "who": "Specialist Provider"
      },
      {
        "name": "Incident Activity Logging",
        "time": "Continuous",
        "who": "Direct Travel"
      },
      {
        "name": "Status Updates",
        "time": "Every 2 hours",
        "who": "Direct Travel"
      }
    ],
    "steps": [
      {
        "title": "Incident Detected",
        "desc": "A magnitude 6.1 earthquake is reported near Tokyo. The agent begins by querying the Incident entity to understand the event type and determine the appropriate response path.",
        "nodes": [
          "incident"
        ],
        "edges": [],
        "focus": "incident",
        "log": [
          {
            "cls": "qry",
            "text": "QUERY  get_entity(\"incident\")"
          },
          {
            "cls": "atr",
            "text": "READ   type=Incident"
          },
          {
            "cls": "atr",
            "text": "READ   categories: security, natural hazards, health, transport, political, infrastructure"
          },
          {
            "cls": "dec",
            "text": "DECISION  Classify severity and determine response chain"
          }
        ]
      },
      {
        "title": "Severity Classification",
        "desc": "Agent traverses CLASSIFIED_AS edge to severity framework. Level 3: \"Action Required\" — outreach within 60 minutes, client escalation within 60 minutes, status updates every 2 hours.",
        "nodes": [
          "severity_level_3"
        ],
        "edges": [
          "r93"
        ],
        "focus": "severity_level_3",
        "manual": "Without the graph, an agent manually opens the policy PDF, finds the severity table, cross-references timing columns, and checks crisis bridge requirements. 3–5 minutes per lookup.",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  incident ──CLASSIFIED_AS──▶ severity_level_3"
          },
          {
            "cls": "atr",
            "text": "READ   alert_time_target: within 60 minutes"
          },
          {
            "cls": "atr",
            "text": "READ   client_escalation_time_target: within 60 minutes"
          },
          {
            "cls": "atr",
            "text": "READ   status_update_cadence: Every 2 hours while active"
          },
          {
            "cls": "dec",
            "text": "DECISION  Crisis Bridge NOT required (Level 4 only)"
          }
        ]
      },
      {
        "title": "Service Activation",
        "desc": "Agent queries all services with ACTIVATED_AT edges to severity_level_3. Five services activate: incident response, client escalation, rebooking, specialist coordination, and locate assistance.",
        "nodes": [
          "incident_response_service",
          "client_escalation_service",
          "rebooking_disruption_support_service",
          "specialist_provider_coordination_service",
          "locate_assistance_service"
        ],
        "edges": [
          "r304",
          "r306",
          "r308",
          "r310",
          "r135"
        ],
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  * ──ACTIVATED_AT──▶ severity_level_3"
          },
          {
            "cls": "atr",
            "text": "FOUND  Incident Response ✓  Client Escalation ✓  Rebooking ✓"
          },
          {
            "cls": "atr",
            "text": "FOUND  Specialist Coordination ✓  Locate Assistance ✓"
          },
          {
            "cls": "dec",
            "text": "DECISION  3 of 5 services require Client authorization"
          }
        ]
      },
      {
        "title": "Welfare Check Workflow → Alert Cascade",
        "desc": "Welfare check workflow activates. Three alert channels fire in sequence: SMS → Email → Voice. Each is a STEP_OF the workflow, connected by FOLLOWED_BY edges.",
        "nodes": [
          "welfare_check_workflow",
          "alert_level_3_sms",
          "alert_level_3_email",
          "alert_level_3_voice"
        ],
        "edges": [
          "r285",
          "r279",
          "r280",
          "r281",
          "r287",
          "r288"
        ],
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  welfare_check_workflow ──CONDITIONAL_ON──▶ severity_level_3"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  alert_level_3_sms ──FOLLOWED_BY──▶ alert_level_3_email"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  alert_level_3_email ──FOLLOWED_BY──▶ alert_level_3_voice"
          },
          {
            "cls": "dec",
            "text": "CHAIN  SMS → Email → Voice (all STEP_OF welfare_check)"
          }
        ]
      },
      {
        "title": "Alerts Sent to Traveler",
        "desc": "All three alert channels have SENT_TO edges to traveler. The SMS template reads: \"TRAVEL ALERT: [EVENT TYPE] in [CITY]. Are you safe? Reply: SAFE / NEED HELP / NOT IN AREA.\"",
        "nodes": [
          "traveler"
        ],
        "edges": [
          "r264",
          "r265",
          "r266"
        ],
        "focus": "alert_level_3_sms",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  alert_level_3_sms ──SENT_TO──▶ traveler"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  alert_level_3_email ──SENT_TO──▶ traveler"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  alert_level_3_voice ──SENT_TO──▶ traveler"
          },
          {
            "cls": "qry",
            "text": "ACTION  SMS sent at T+8 min (SLO: 60 min ✓)"
          }
        ]
      },
      {
        "title": "Traveler Responds: NEED ASSISTANCE",
        "desc": "Traveler replies NEED ASSISTANCE. Graph traversal reads the response status entity’s tmc_action attribute: \"Attempt live contact (voice call) within 15 minutes.\"",
        "nodes": [
          "traveler_response_need_assistance",
          "need_assistance_live_contact_obligation"
        ],
        "edges": [
          "r61",
          "r96"
        ],
        "focus": "traveler_response_need_assistance",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  traveler ──RESPONDS_WITH──▶ NEED_ASSISTANCE"
          },
          {
            "cls": "atr",
            "text": "READ   tmc_action: live contact within 15 minutes"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  NEED_ASSISTANCE ──FOLLOWED_BY──▶ live_contact_obligation"
          },
          {
            "cls": "dec",
            "text": "DECISION  Initiate voice call immediately"
          }
        ]
      },
      {
        "title": "Authorization Chain",
        "desc": "NEED_ASSISTANCE triggers three services. All three have REQUIRES_AUTHORIZATION_FROM edges to Client. Standard rebooking proceeds; extraordinary measures require express Client authorization.",
        "nodes": [
          "client"
        ],
        "edges": [
          "r94",
          "r58",
          "r59",
          "r55",
          "r56",
          "r57"
        ],
        "manual": "Without the graph, an agent must recall from training which services need Client authorization and which can proceed immediately. Under pressure, authorization gates are often skipped or delayed.",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  NEED_ASSISTANCE ──TRIGGERS_ACTION──▶ incident_response"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  NEED_ASSISTANCE ──TRIGGERS_ACTION──▶ rebooking_support"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  NEED_ASSISTANCE ──TRIGGERS_ACTION──▶ specialist_coordination"
          },
          {
            "cls": "wrn",
            "text": "AUTH   All 3 services ──REQUIRES_AUTH──▶ client"
          },
          {
            "cls": "dec",
            "text": "DECISION  Standard rebooking: proceed. Extraordinary: request Client auth."
          }
        ]
      },
      {
        "title": "Client Escalation Contacts",
        "desc": "Agent follows ESCALATED_TO edges from severity_level_3 to determine the full notification chain. Five contact roles, each with defined escalation conditions.",
        "nodes": [
          "primary_travel_program_owner",
          "alternate_travel_program_contact",
          "after_hours_duty_contact",
          "corporate_security_contact",
          "human_resources_duty_contact"
        ],
        "edges": [
          "r118",
          "r312",
          "r313",
          "r120",
          "r314"
        ],
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  severity_level_3 ──ESCALATED_TO──▶ [5 contacts]"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  Primary Travel Program Owner (mandatory)"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  Alternate Contact (backup)"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  Corporate Security (security-adjacent incident)"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  HR Duty Contact (welfare concern)"
          },
          {
            "cls": "dim",
            "text": "SKIP   Senior Leadership (Level 4 only per roster_position: 6)"
          }
        ]
      }
    ]
  },
  {
    "id": "non_responsive",
    "name": "🔇 Non-Responsive Traveler — Escalation Workflow",
    "desc": "6-step workflow chain: no response → escalation notification → locate assistance → specialist provider engagement",
    "severity": "high",
    "sevLabel": "Level 3 — Escalation Required",
    "incidentLabel": "Non-Responsive Traveler — Lagos, Nigeria",
    "actions": [
      {
        "name": "Welfare Check Outreach",
        "time": "3 attempts / 2 channels / 90 min",
        "who": "Direct Travel"
      },
      {
        "name": "Non-Responsive Escalation Trigger",
        "time": "After 90 min threshold",
        "who": "Direct Travel"
      },
      {
        "name": "Escalation Notification to Client",
        "time": "Immediate after threshold",
        "who": "Primary + HR Contacts"
      },
      {
        "name": "Locate Assistance Authorization",
        "time": "Upon Client approval",
        "who": "Client"
      },
      {
        "name": "On-Ground Locate Deployment",
        "time": "Upon authorization",
        "who": "Specialist Provider"
      },
      {
        "name": "Status Updates",
        "time": "Every 2 hours",
        "who": "Direct Travel"
      }
    ],
    "steps": [
      {
        "title": "Welfare Check — No Response",
        "desc": "Traveler has not responded to welfare check outreach. Agent reads the NO_RESPONSE status entity: \"3 contacts across 2 channels over 90 minutes, then escalate.\"",
        "nodes": [
          "traveler",
          "traveler_response_no_response",
          "welfare_check_workflow"
        ],
        "edges": [
          "r63",
          "r285"
        ],
        "focus": "traveler_response_no_response",
        "manual": "An agent must recall the exact 3-attempt / 2-channel / 90-minute threshold from memory. Getting any parameter wrong delays escalation.",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  traveler ──RESPONDS_WITH──▶ NO_RESPONSE"
          },
          {
            "cls": "atr",
            "text": "READ   tmc_action: 3 contacts / 2 channels / 90 min, then escalate"
          },
          {
            "cls": "atr",
            "text": "READ   triggers_escalation: true"
          },
          {
            "cls": "dec",
            "text": "CHECK  Threshold met? YES — 90 min elapsed, 3 attempts made"
          }
        ]
      },
      {
        "title": "Escalation Workflow Triggered",
        "desc": "NO_RESPONSE triggers the non-responsive traveler escalation workflow via FOLLOWED_BY edge. The welfare check workflow chains into the escalation workflow.",
        "nodes": [
          "non_responsive_traveler_escalation_workflow"
        ],
        "edges": [
          "r95",
          "r343"
        ],
        "focus": "non_responsive_traveler_escalation_workflow",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  NO_RESPONSE ──FOLLOWED_BY──▶ non_responsive_escalation_workflow"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  welfare_check ──FOLLOWED_BY──▶ non_responsive_escalation_workflow"
          },
          {
            "cls": "atr",
            "text": "READ   step_count: 3, time_constraint: 90 minutes"
          },
          {
            "cls": "dec",
            "text": "DECISION  Begin 3-step escalation sequence"
          }
        ]
      },
      {
        "title": "Escalation Notification",
        "desc": "First step: escalation notification sent to Client contacts with traveler details, last known location, outreach attempts, and supplier information.",
        "nodes": [
          "escalation_notification"
        ],
        "edges": [
          "r141",
          "r143"
        ],
        "focus": "escalation_notification",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  welfare_check ──FOLLOWED_BY──▶ escalation_notification"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  escalation_notification ──STEP_OF──▶ non_responsive_workflow"
          },
          {
            "cls": "atr",
            "text": "READ   content: traveler name, itinerary, last known location, attempts made"
          },
          {
            "cls": "dec",
            "text": "ACTION  Notification compiled and sent to escalation contacts"
          }
        ]
      },
      {
        "title": "Client Contacts Notified",
        "desc": "Agent follows ESCALATED_TO edges from severity_level_3 to identify required notification targets. HR is notified due to welfare concern.",
        "nodes": [
          "severity_level_3",
          "primary_travel_program_owner",
          "human_resources_duty_contact",
          "corporate_security_contact"
        ],
        "edges": [
          "r118",
          "r120",
          "r314",
          "r130"
        ],
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  severity_level_3 ──ESCALATED_TO──▶ primary_travel_program_owner"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  severity_level_3 ──ESCALATED_TO──▶ corporate_security_contact"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  severity_level_3 ──ESCALATED_TO──▶ human_resources_duty_contact"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  Primary + Security + HR (welfare concern in high-risk location)"
          }
        ]
      },
      {
        "title": "Locate Assistance Authorized",
        "desc": "Escalation notification chains to locate assistance via FOLLOWED_BY. Locate requires Client authorization and activates at Level 3+.",
        "nodes": [
          "locate_assistance_service",
          "client"
        ],
        "edges": [
          "r142",
          "r134",
          "r144",
          "r135"
        ],
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  escalation_notification ──FOLLOWED_BY──▶ locate_assistance_service"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  locate_assistance ──STEP_OF──▶ non_responsive_workflow"
          },
          {
            "cls": "wrn",
            "text": "AUTH   locate_assistance ──REQUIRES_AUTH──▶ client"
          },
          {
            "cls": "dec",
            "text": "REQUEST  Client authorization for on-ground locate"
          },
          {
            "cls": "dec",
            "text": "AUTHORIZED  Client approves locate deployment"
          }
        ]
      },
      {
        "title": "Specialist Provider Engaged",
        "desc": "Direct Travel engages a specialist provider for on-ground locate assistance. Both Direct Travel and the specialist provider have PROVIDES edges to the locate service.",
        "nodes": [
          "specialist_provider",
          "direct_travel_inc"
        ],
        "edges": [
          "r139",
          "r138",
          "r31"
        ],
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  specialist_provider ──PROVIDES──▶ locate_assistance_service"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  direct_travel ──PROVIDES──▶ locate_assistance_service"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  direct_travel ──ENGAGES──▶ specialist_provider"
          },
          {
            "cls": "dec",
            "text": "DEPLOYED  On-ground locate team dispatched to last known location"
          }
        ]
      }
    ]
  },
  {
    "id": "crisis_bridge",
    "name": "🚨 Level 4 Crisis — Crisis Bridge & SITREP Chain",
    "desc": "7-step crisis response: crisis bridge activation → alert cascade → SITREP delivery → full escalation → post-incident review",
    "severity": "critical",
    "sevLabel": "Level 4 — Crisis",
    "incidentLabel": "Terrorist Attack — London, UK",
    "actions": [
      {
        "name": "Level 4 Alert (SMS/Email/Voice)",
        "time": "< 30 min (SLO)",
        "who": "Direct Travel"
      },
      {
        "name": "Crisis Bridge Activation",
        "time": "< 60 min",
        "who": "Direct Travel"
      },
      {
        "name": "SITREP — Acute Phase",
        "time": "Every 30 min",
        "who": "Direct Travel"
      },
      {
        "name": "SITREP — Sustained Phase",
        "time": "Every 60 min",
        "who": "Direct Travel"
      },
      {
        "name": "Senior Leadership Notification",
        "time": "< 30 min",
        "who": "Senior Leadership Contact"
      },
      {
        "name": "All-Contact Escalation",
        "time": "< 30 min",
        "who": "Full Escalation Roster"
      },
      {
        "name": "Post-Incident Review",
        "time": "Within 30 days",
        "who": "Both Parties"
      }
    ],
    "steps": [
      {
        "title": "Level 4 Crisis Declared",
        "desc": "Incident classified at highest severity. Level 4: \"Crisis\" — alerts within 30 minutes, escalation within 30 minutes, SITREPs every 30 minutes during acute phase.",
        "nodes": [
          "incident",
          "severity_level_4"
        ],
        "edges": [
          "r71"
        ],
        "focus": "severity_level_4",
        "log": [
          {
            "cls": "qry",
            "text": "ALERT  Level 4 Crisis — London, UK"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  incident ──CLASSIFIED_AS──▶ severity_level_4"
          },
          {
            "cls": "atr",
            "text": "READ   level: 4, classification: Crisis"
          },
          {
            "cls": "atr",
            "text": "READ   alert_time_target: within 30 minutes"
          },
          {
            "cls": "atr",
            "text": "READ   status_update_cadence: Every 30 min (acute) / 60 min (sustained)"
          }
        ]
      },
      {
        "title": "Crisis Bridge Activation",
        "desc": "Crisis Bridge is the only service with ACTIVATED_AT → severity_level_4 specifically. The activation workflow must complete within 60 minutes of Level 4 determination.",
        "nodes": [
          "crisis_bridge",
          "crisis_bridge_activation_workflow"
        ],
        "edges": [
          "r250",
          "r104",
          "r254"
        ],
        "focus": "crisis_bridge_activation_workflow",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  crisis_bridge ──ACTIVATED_AT──▶ severity_level_4"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  crisis_bridge_activation_workflow ──CONDITIONAL_ON──▶ severity_level_4"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  crisis_bridge ──STEP_OF──▶ crisis_bridge_activation_workflow"
          },
          {
            "cls": "atr",
            "text": "READ   time_constraint: within 60 minutes of Level 4 determination"
          },
          {
            "cls": "dec",
            "text": "ACTION  Activate Crisis Bridge communication channel"
          }
        ]
      },
      {
        "title": "Level 4 Alert Cascade",
        "desc": "Three alert channels fire in FOLLOWED_BY sequence: SMS → Email → Voice. All are STEP_OF welfare check workflow and SENT_TO traveler.",
        "nodes": [
          "welfare_check_workflow",
          "alert_level_4_sms",
          "alert_level_4_email",
          "alert_level_4_voice",
          "traveler"
        ],
        "edges": [
          "r286",
          "r282",
          "r283",
          "r284",
          "r289",
          "r290",
          "r267",
          "r268",
          "r269"
        ],
        "focus": "alert_level_4_sms",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  welfare_check ──CONDITIONAL_ON──▶ severity_level_4"
          },
          {
            "cls": "trv",
            "text": "CHAIN  alert_level_4_sms ──FOLLOWED_BY──▶ email ──FOLLOWED_BY──▶ voice"
          },
          {
            "cls": "trv",
            "text": "ALL    ──SENT_TO──▶ traveler"
          },
          {
            "cls": "atr",
            "text": "READ   SMS: CRISIS ALERT: [EVENT TYPE] in [CITY]. Reply SAFE or NEED HELP now."
          },
          {
            "cls": "dec",
            "text": "ACTION  All 3 channels dispatched at T+12 min (SLO: 30 min ✓)"
          }
        ]
      },
      {
        "title": "SITREP Delivery Chain",
        "desc": "Level 4 activates SITREP reporting. Two phases connected by FOLLOWED_BY: Acute (every 30 min) transitions to Sustained (every 60 min). Both are STEP_OF the crisis bridge workflow.",
        "nodes": [
          "sitrep",
          "sitrep_level_4_acute",
          "sitrep_level_4_sustained"
        ],
        "edges": [
          "r132",
          "r253",
          "r344",
          "r345",
          "r145"
        ],
        "focus": "sitrep",
        "manual": "SITREP content includes: event status, traveler counts by status (safe/need assistance/non-responsive/not in area), actions taken, recommended next steps, and resource utilization.",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  sitrep ──CONDITIONAL_ON──▶ severity_level_4"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  sitrep_acute ──FOLLOWED_BY──▶ sitrep_sustained"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  sitrep_acute ──STEP_OF──▶ crisis_bridge_activation_workflow"
          },
          {
            "cls": "atr",
            "text": "READ   Acute: every 30 min → Sustained: every 60 min"
          },
          {
            "cls": "dec",
            "text": "ACTION  First SITREP delivered at T+30 min"
          }
        ]
      },
      {
        "title": "Full Escalation — All Contacts",
        "desc": "Level 4 triggers ESCALATED_TO edges to all contact roles, including Senior Leadership which is Level 4 only.",
        "nodes": [
          "primary_travel_program_owner",
          "alternate_travel_program_contact",
          "after_hours_duty_contact",
          "corporate_security_contact",
          "human_resources_duty_contact",
          "senior_leadership_contact"
        ],
        "edges": [
          "r119",
          "r315",
          "r316",
          "r121",
          "r317",
          "r122"
        ],
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  severity_level_4 ──ESCALATED_TO──▶ [6 contacts]"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  Primary Travel Program Owner (mandatory)"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  Alternate Contact + After-Hours Contact"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  Corporate Security (security incident)"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  HR Duty Contact (welfare concern)"
          },
          {
            "cls": "dec",
            "text": "NOTIFY  Senior Leadership (Level 4 ONLY ✓)"
          }
        ]
      },
      {
        "title": "All Services Activated",
        "desc": "At Level 4, every severity-gated service activates. Post-Incident Reporting is Level 4-exclusive. Direct Travel provides all services; 3 require Client authorization.",
        "nodes": [
          "direct_travel_inc",
          "post_incident_reporting_service",
          "incident_response_service"
        ],
        "edges": [
          "r305",
          "r307",
          "r309",
          "r311",
          "r53",
          "r136",
          "r40",
          "r41"
        ],
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  * ──ACTIVATED_AT──▶ severity_level_4"
          },
          {
            "cls": "atr",
            "text": "FOUND  Incident Response ✓  Client Escalation ✓  Rebooking ✓"
          },
          {
            "cls": "atr",
            "text": "FOUND  Specialist Coordination ✓  Locate Assistance ✓"
          },
          {
            "cls": "atr",
            "text": "FOUND  Post-Incident Reporting ✓ (Level 4 exclusive)"
          },
          {
            "cls": "dec",
            "text": "DECISION  6 services activated — maximum response posture"
          }
        ]
      },
      {
        "title": "Post-Incident Review",
        "desc": "After resolution, post-incident review is CONDITIONAL_ON both Level 4 and incident. Must occur within 30 days. Incident activity log maintained throughout.",
        "nodes": [
          "post_incident_review",
          "incident_activity_log"
        ],
        "edges": [
          "r234",
          "r235",
          "r237",
          "r291"
        ],
        "focus": "post_incident_review",
        "log": [
          {
            "cls": "trv",
            "text": "TRAVERSE  post_incident_review ──CONDITIONAL_ON──▶ severity_level_4"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  post_incident_review ──CONDITIONAL_ON──▶ incident"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  post_incident_reporting ──STEP_OF──▶ post_incident_review"
          },
          {
            "cls": "atr",
            "text": "READ   time_constraint: Within 30 days of the Level 4 Incident"
          },
          {
            "cls": "trv",
            "text": "TRAVERSE  direct_travel ──OPERATES──▶ incident_activity_log"
          },
          {
            "cls": "dec",
            "text": "COMPLETE  Response documented. Review scheduled within 30 days."
          }
        ]
      }
    ]
  }
];
