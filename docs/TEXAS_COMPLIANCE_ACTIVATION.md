# Texas Outreach Compliance Activation

Texas is a supported acquisition, contract, disposition, and closing market. It is not globally disabled.

Phone and SMS outreach to a Texas property remains fail-closed until SAHJONY has documented the applicable Texas Business & Commerce Code Chapter 302 registration or exemption analysis for its operating model.

## Activation flag

After that business/legal validation is complete, set:

```text
TEXAS_TELEPHONE_SOLICITATION_COMPLIANCE_CONFIRMED=true
```

Do not set this flag merely to bypass the compliance gate. The evidence supporting registration, exemption, or non-applicability should be retained in the business compliance file.

## Gates that still apply after activation

- Fresh national/state DNC evidence for live calls, automated calls, and SMS.
- Entity-specific suppression/opt-out checks.
- Prior express written consent for automated calls and SMS.
- Recipient-local 8 a.m.–9 p.m. outreach window.
- Verified lead/property evidence before external action.
- Human approval for material outreach and transaction actions.

The flag does not authorize a particular transaction structure, legal conclusion, or campaign. It only confirms that the organization has completed the Texas telephone-solicitation registration/exemption analysis needed before the application will evaluate Texas phone/SMS outreach under its remaining evidence gates.
