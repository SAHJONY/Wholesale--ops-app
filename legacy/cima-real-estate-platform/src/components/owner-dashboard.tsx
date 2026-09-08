// Owner Dashboard Component
// Private dashboard for authenticated owners

import { ownerLogout } from '../config/owner-auth';

interface OwnerDashboardProps {
  ownerData: any;
  onLogout: () => void;
}

export function OwnerDashboard({ ownerData, onLogout }: OwnerDashboardProps) {
  const handleLogout = async () => {
    await ownerLogout();
    onLogout();
  };

  return (
    <div className="owner-dashboard-container">
      <div className="owner-dashboard-header">
        <h1>Owner Dashboard</h1>
        <button onClick={handleLogout} className="logout-btn">
          Logout
        </button>
      </div>

      <div className="owner-dashboard-content">
        <div className="owner-info-card">
          <h2>Owner Information</h2>
          <div className="info-grid">
            <div className="info-item">
              <span className="label">Name:</span>
              <span className="value">{ownerData.name || 'Juan Gonzalez'}</span>
            </div>
            <div className="info-item">
              <span className="label">Email:</span>
              <span className="value">{ownerData.email || 'sahjonycapitalllc@outlook.com'}</span>
            </div>
            <div className="info-item">
              <span className="label">Phone:</span>
              <span className="value">{ownerData.phone || '+167****6284'}</span>
            </div>
            <div className="info-item">
              <span className="label">Company:</span>
              <span className="value">SAHJONY CAPITAL LLC</span>
            </div>
          </div>
        </div>

        <div className="platform-status-card">
          <h2>Platform Status</h2>
          <div className="status-grid">
            <div className="status-item">
              <span className="status-label">Deployment Status:</span>
              <span className="status-value status-active">✅ Active</span>
            </div>
            <div className="status-item">
              <span className="status-label">Bland.ai Balance:</span>
              <span className="status-value">$55.16</span>
            </div>
            <div className="status-item">
              <span className="status-label">AI Model:</span>
              <span className="status-value">DeepSeek V3.1 Terminus</span>
            </div>
            <div className="status-item">
              <span className="status-label">Environment:</span>
              <span className="status-value">Production</span>
            </div>
          </div>
        </div>

        <div className="business-metrics-card">
          <h2>Business Metrics</h2>
          <div className="metrics-grid">
            <div className="metric-item">
              <span className="metric-value">0</span>
              <span className="metric-label">Total Leads</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">0</span>
              <span className="metric-label">Offers Sent</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">0</span>
              <span className="metric-label">Contracts</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">$0</span>
              <span className="metric-label">Projected Profit</span>
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        .owner-dashboard-container {
          min-height: 100vh;
          background: #f5f7fa;
          padding: 20px;
        }

        .owner-dashboard-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 30px;
          padding: 20px;
          background: white;
          border-radius: 12px;
          box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }

        .owner-dashboard-header h1 {
          margin: 0;
          color: #333;
          font-size: 28px;
          font-weight: 600;
        }

        .logout-btn {
          background: #e74c3c;
          color: white;
          border: none;
          padding: 10px 20px;
          border-radius: 6px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          transition: background 0.2s;
        }

        .logout-btn:hover {
          background: #c0392b;
        }

        .owner-dashboard-content {
          display: grid;
          gap: 20px;
          grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        }

        .owner-info-card,
        .platform-status-card,
        .business-metrics-card {
          background: white;
          border-radius: 12px;
          padding: 25px;
          box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }

        .owner-info-card h2,
        .platform-status-card h2,
        .business-metrics-card h2 {
          margin: 0 0 20px 0;
          color: #333;
          font-size: 20px;
          font-weight: 600;
        }

        .info-grid {
          display: grid;
          gap: 15px;
        }

        .info-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 10px 0;
          border-bottom: 1px solid #f0f0f0;
        }

        .info-item:last-child {
          border-bottom: none;
        }

        .label {
          color: #666;
          font-weight: 500;
        }

        .value {
          color: #333;
          font-weight: 600;
        }

        .status-grid {
          display: grid;
          gap: 15px;
        }

        .status-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 0;
        }

        .status-label {
          color: #666;
        }

        .status-value {
          color: #333;
          font-weight: 600;
        }

        .status-active {
          color: #27ae60;
        }

        .metrics-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 20px;
        }

        .metric-item {
          text-align: center;
          padding: 15px;
          background: #f8f9fa;
          border-radius: 8px;
        }

        .metric-value {
          display: block;
          font-size: 24px;
          font-weight: 700;
          color: #667eea;
          margin-bottom: 5px;
        }

        .metric-label {
          color: #666;
          font-size: 14px;
        }
      `}</style>
    </div>
  );
}