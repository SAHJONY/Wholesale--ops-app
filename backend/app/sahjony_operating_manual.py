from __future__ import annotations

"""Canonical SAHJONY Wholesale operating manual and communication library.

This module contains business policy and approved communication language. It does
not authorize outreach. All outbound use remains subject to owner/contact
verification, DNC/consent, jurisdictional rules, and the outbound compliance
engine.
"""

SAHJONY_PLAYBOOKS = [
    (
        "SAHJONY Master Operating Manual",
        "management",
        [
            "MISSION: acquire and assign profitable off-market real-estate opportunities through verified data, disciplined underwriting, respectful seller communication, verified buyers, and documented closings.",
            "FOCUS: single-family residential off-market opportunities first; vacant lots may be pursued when land due diligence supports a clear investor or builder exit.",
            "PROPERTY INTAKE STANDARD: every property enters with full address, source provenance, property identity, and an owner-resolution task. Add APN, legal description, county/tax account and distress evidence when available.",
            "OWNER STANDARD: never promote a person to owner-of-record without authoritative ownership evidence. Address-associated people remain candidates until verified.",
            "CONTACT STANDARD: Contact Ready requires the owner/address resolution gate plus independent corroboration of the same contact and the required confidence threshold. Contact Ready does not equal Outreach Authorized.",
            "QUALIFICATION: use the four pillars on every seller opportunity — Motivation, Timeline, Condition, Price.",
            "UNDERWRITING: MAO = (ARV × 0.70) − estimated repairs − assignment fee. Aggressive opening offer = MAO × 0.85. Hard walkaway ceiling = MAO.",
            "OFFER TIERS: present an aggressive cash opening, MAO target, and a creative financing/novation alternative when a cash offer does not work and the structure is appropriate.",
            "TARGET ECONOMICS: prioritize deals capable of strong buyer margin and meaningful assignment revenue; do not force a contract that destroys buyer economics.",
            "OUTREACH: seller communication must be empathetic, professional, consultative, direct, and low pressure. Emphasize as-is purchase, convenience, speed, flexible closing, and closing-cost simplicity only when accurate.",
            "COMPLIANCE: no automated call or text is authorized until the applicable owner/contact, DNC, consent, timezone, state and channel gates pass. Honor opt-outs immediately.",
            "VOICE: use a natural personal representative name and SAHJONY company identity. Do not claim facts, authority, ownership, offers, approvals, or timelines that have not been verified. No call recording unless separately authorized and compliant.",
            "DISPOSITION: market only contractually controlled opportunities. Require deal-specific buyer fit, assignment acceptance, proof of funds and closing ability before calling a buyer Deal Ready.",
            "BUYER STANDARD: Buyer Candidate → Buying Box Verified → POF Verified → Assignment Friendly → Deal Ready.",
            "TITLE/CLOSING: verify seller authority, title chain, payoff/liens, executed purchase agreement, earnest money, buyer funds, assignment agreement, settlement statement and funding before recording revenue.",
            "TRUTH POLICY: never manufacture positive outcomes. Unknown remains unknown; candidate remains candidate; pending proof remains pending.",
            "SELF-HEALING POLICY: retry transient failures and switch only to authorized alternate sources. Never bypass access controls, paywalls, authentication, compliance gates or evidence requirements.",
            "SELF-IMPROVEMENT POLICY: optimize conversion, speed, evidence quality and profitability without changing protected underwriting/compliance rules autonomously.",
            "CORE WEEKLY KPIs: qualified properties, verified owners, Contact Ready leads, seller conversations, offers, contracts, closings, assignment revenue, average assignment fee, days-to-cash, cost per closed deal.",
        ],
    ),
    (
        "Daily Acquisition Operating Rhythm",
        "acquisitions",
        [
            "Review highest-priority distress and stacked-motivation properties first.",
            "Resolve property identity and official county/parcel evidence before owner promotion.",
            "Work owner-resolution tasks until each lead is verified, likely with explicit limits, or blocked with a concrete next action.",
            "Only move verified and compliant contacts into seller communication queues.",
            "Capture Motivation, Timeline, Condition and Price from every substantive seller conversation.",
            "Underwrite qualified opportunities using supported ARV, conservative repair scope, assignment target and the 70% rule.",
            "Send offers only after required hard blockers have cleared; schedule a specific next follow-up for every live seller.",
        ],
    ),
    (
        "Seller Qualification and Negotiation",
        "acquisitions",
        [
            "Open by confirming the correct person and whether it is a good time to speak.",
            "Explain SAHJONY simply: a real-estate investment company evaluating an as-is purchase.",
            "Ask why the owner is considering a sale now; listen before discussing price.",
            "Ask desired timing and any deadlines or property-related pressure without exploiting distress.",
            "Ask condition questions room-by-room and system-by-system; never argue with the seller about condition.",
            "Ask what outcome or price would make the sale worthwhile for the seller.",
            "Summarize what you heard and confirm accuracy before presenting numbers.",
            "Anchor with the approved opening offer only when underwriting is complete. Explain the tradeoff: lower cash price in exchange for as-is convenience, speed and fewer contingencies.",
            "If price is too far apart, explore timing, terms, seller finance or novation only when legally and operationally appropriate.",
            "Never exceed MAO without a separately approved economic rationale.",
        ],
    ),
    (
        "Contract-to-Close",
        "transaction",
        [
            "Confirm executed purchase agreement and assignment rights.",
            "Deposit earnest money according to the executed agreement.",
            "Open title with an appropriate closing partner and verify seller authority.",
            "Resolve payoff, tax, HOA, judgment and title exceptions.",
            "Coordinate property access and final condition evidence.",
            "Match qualified buyers by ZIP, asset type, price, rehab tolerance and closing timeline.",
            "Require proof of funds and assignment acceptance before buyer promotion to Deal Ready.",
            "Execute assignment agreement, verify settlement statement, confirm funding and record final assignment revenue only after closing evidence exists.",
        ],
    ),
    (
        "Disposition and Buyer Control",
        "disposition",
        [
            "Create a concise deal packet with ARV support, repair estimate, assignment price, property facts, access terms and closing timeline.",
            "Do not expose unverified facts as certain. Label estimates and pending diligence clearly.",
            "Rank buyers by actual buying box, recent activity, POF, assignment acceptance and closing reliability.",
            "Request deal-specific price confirmation and proof of funds before reserving the deal.",
            "Use competition ethically: communicate actual deadlines and actual competing interest only.",
            "Select the strongest executable buyer, not merely the highest verbal number.",
        ],
    ),
    (
        "Weekly Owner Scorecard",
        "management",
        [
            "Review new qualified properties and stacked-distress count.",
            "Review owner-verified rate and Contact Ready rate.",
            "Review seller conversations, offers, contracts and contract-to-close conversion.",
            "Review buyer coverage by active ZIP and count of POF-verified Deal Ready buyers.",
            "Review assignment revenue collected, average assignment fee, days-to-cash and cost per closed deal.",
            "Review blocked tasks and require a concrete recovery path for every critical blocker.",
            "Choose the three highest-leverage operating priorities for the next seven days.",
        ],
    ),
    (
        "Communication Standards",
        "communication",
        [
            "Tone: empathetic, professional, consultative, concise and direct; never aggressive or manipulative.",
            "Identify the representative by personal name and SAHJONY. Do not misrepresent identity, authority, ownership or legal status.",
            "Lead with relevance and permission, not pressure.",
            "Use plain language. Avoid investor jargon with sellers unless the seller uses it first.",
            "Never promise a price, closing date, title outcome or buyer until verified.",
            "Never use a seller's distress as a threat or artificial urgency tactic.",
            "When the seller says no, respect the answer and ask permission before any future follow-up.",
            "Honor STOP/opt-out and channel preferences immediately.",
            "Buyer communication is metric-driven: ARV, repairs, assignment price, access, closing date, POF requirement and material risks.",
            "JV communication is transparent about control of contract, responsibilities, fee split, buyer ownership, title process and non-circumvention terms.",
        ],
    ),
]

SAHJONY_SMS_TEMPLATES = [
    {
        "name": "SAHJONY Seller — Permission First",
        "pathway_id": "seller_initial",
        "persona_id": "sahjony_acquisitions",
        "body": "Hi {{first_name}}, this is {{rep_name}} with SAHJONY. I'm reaching out about {{property_address}}. Would you be open to a brief conversation about a possible as-is sale? If not, no problem. Reply STOP to opt out.",
    },
    {
        "name": "SAHJONY Seller — Warm Follow-Up",
        "pathway_id": "seller_follow_up",
        "persona_id": "sahjony_acquisitions",
        "body": "Hi {{first_name}}, {{rep_name}} with SAHJONY following up on {{property_address}}. I wanted to see whether selling is still something you'd consider and, if so, what timing works best for you. Reply STOP to opt out.",
    },
    {
        "name": "SAHJONY Seller — Appointment Confirmation",
        "pathway_id": "seller_appointment",
        "persona_id": "sahjony_acquisitions",
        "body": "Hi {{first_name}}, confirming our conversation about {{property_address}} for {{appointment_time}}. We'll review your goals, timing and the property's condition so we can determine whether an as-is purchase makes sense. — {{rep_name}}, SAHJONY",
    },
    {
        "name": "SAHJONY Seller — Offer Follow-Up",
        "pathway_id": "seller_offer_follow_up",
        "persona_id": "sahjony_acquisitions",
        "body": "Hi {{first_name}}, checking in regarding the offer for {{property_address}}. If the cash price doesn't solve what you need, I can also review whether another structure may fit better. No pressure either way. — {{rep_name}}, SAHJONY",
    },
    {
        "name": "SAHJONY Seller — Respectful Closeout",
        "pathway_id": "seller_closeout",
        "persona_id": "sahjony_acquisitions",
        "body": "Hi {{first_name}}, I'll close out my follow-up on {{property_address}} for now. If circumstances change and you'd like to discuss an as-is sale later, you can reach me here. Wishing you the best. — {{rep_name}}, SAHJONY",
    },
    {
        "name": "SAHJONY Buyer — Buying Box Verification",
        "pathway_id": "buyer_verification",
        "persona_id": "sahjony_disposition",
        "body": "Hi {{first_name}}, {{rep_name}} with SAHJONY. I'm updating our buyer list for {{market}}. Are you actively buying {{property_type}} there? If yes, please send your price range, rehab tolerance, preferred ZIPs, closing timeframe and current POF.",
    },
    {
        "name": "SAHJONY Buyer — Deal Alert",
        "pathway_id": "buyer_deal_alert",
        "persona_id": "sahjony_disposition",
        "body": "OFF-MARKET {{city}}, {{state}} {{zip}} | ARV {{arv}} | Repairs est. {{repairs}} | Assignment price {{assignment_price}} | {{beds}}/{{baths}}, {{sqft}} sf. POF required. Reply INTERESTED for the packet/access details. — SAHJONY",
    },
    {
        "name": "SAHJONY Buyer — POF and Price Confirmation",
        "pathway_id": "buyer_pof",
        "persona_id": "sahjony_disposition",
        "body": "Thanks for the interest in {{property_short}}. To confirm your position, please send current POF, your best executable price, assignment acceptance and earliest closing date. We will select based on certainty of close as well as price. — SAHJONY",
    },
    {
        "name": "SAHJONY JV — Initial Review",
        "pathway_id": "jv_intake",
        "persona_id": "sahjony_jv",
        "body": "Hi {{first_name}}, thanks for sending the opportunity to SAHJONY. Please send the executed contract, property address, contract price, access details, closing date, title company, assignment rights and your proposed JV split. We'll review the numbers and buyer fit before confirming participation.",
    },
]

SAHJONY_VOICE_SCRIPTS = {
    "seller_opening": [
        "Hi, is this {{first_name}}? This is {{rep_name}} with SAHJONY. Did I catch you at an okay time for a quick question about {{property_address}}?",
        "We're a real-estate investment company and we're evaluating whether an as-is purchase could make sense. I'm not calling to pressure you — I first wanted to ask whether selling is something you'd consider.",
    ],
    "four_pillars": [
        "Motivation: What has you considering a sale now?",
        "Timeline: If you decided to sell, when would you ideally want everything completed?",
        "Condition: What repairs or updates do you think the property needs today?",
        "Price: What would you need to walk away with for a sale to make sense to you?",
    ],
    "price_objection": [
        "I understand. If you sold conventionally, you might be able to target a higher retail price. Our number has to account for the as-is condition, repairs, holding costs and the convenience of a simpler cash transaction.",
        "If the cash number is too far from what you need, I'd rather be transparent than push you. We can see whether timing or another structure changes the picture.",
    ],
    "not_ready": [
        "That's completely fine. Would you prefer that I close this out, or would it be useful for me to check back at a specific time you choose?",
    ],
    "buyer_call": [
        "Hi {{first_name}}, this is {{rep_name}} with SAHJONY. I have an off-market opportunity in {{zip}} that may match your buying box. Before I send the full packet, are you actively buying there right now?",
        "I'll send the deal metrics. If it fits, we'll need your executable price, current proof of funds, assignment acceptance and closing timeframe.",
    ],
}
