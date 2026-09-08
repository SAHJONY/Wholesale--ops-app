// Sahjony Capital LLC Configuration
// Company branding and domain configuration

export const COMPANY_CONFIG = {
  name: "SAHJONY CAPITAL LLC",
  domains: ["www.sahjonycapital.com", "sahjonycapital.com"],
  phone: "+16783466284",
  email: "sahjonycapitalllc@outlook.com",
  primaryContact: "Juan Gonzalez",
  contractSignatory: "Juan Gonzalez and/or assigns",
  branding: {
    primaryColor: "#1e40af", // Blue
    secondaryColor: "#10b981", // Green
    accentColor: "#f59e0b", // Amber
    logo: "/assets/sahjony-capital-logo.svg",
    favicon: "/assets/favicon.ico"
  },
  business: {
    type: "Real Estate Wholesale",
    portfolioSize: 10,
    phase: "Phase 3",
    focus: "AI-Powered Real Estate Operations"
  },
  contact: {
    primaryContact: "Juan Gonzalez",
    contractSignatory: "Juan Gonzalez and/or assigns",
    address: "Houston, Texas",
    website: "https://www.sahjonycapital.com",
    supportEmail: "sahjonycapitalllc@outlook.com",
    phone: "+16783466284"
  },
  integration: {
    hermesBrain: true,
    primaryAIProvider: "nvidia",
    primaryModel: "deepseek-ai/DeepSeek-V3.1-Terminus",
    blandAI: {
      balance: 55.16,
      enabled: true,
      voice: "alex"
    },
    multiAgent: {
      propertyAnalysis: true,
      crm: true,
      callAutomation: true,
      portfolioManagement: true
    },
    advancedTools: {
      ana: true,
      claw3d: true,
      mirofish: true,
      paperclip: true,
      claudeCode: true,
      kaliLinuxSuite: true
    }
  }
} as const;

// Export individual configs for easy access
export const COMPANY_NAME = COMPANY_CONFIG.name;
export const COMPANY_DOMAINS = COMPANY_CONFIG.domains;
export const COMPANY_PHONE = COMPANY_CONFIG.phone;
export const COMPANY_EMAIL = COMPANY_CONFIG.email;
export const BRANDING_CONFIG = COMPANY_CONFIG.branding;
export const BUSINESS_CONFIG = COMPANY_CONFIG.business;
export const CONTACT_CONFIG = COMPANY_CONFIG.contact;
export const INTEGRATION_CONFIG = COMPANY_CONFIG.integration;