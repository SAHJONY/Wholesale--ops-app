// Owner Login Component
// Private owner authentication interface

import { useState } from 'react';
import { ownerLogin } from '../config/owner-auth';

interface OwnerLoginProps {
  onLoginSuccess: (ownerData: any) => void;
}

export function OwnerLogin({ onLoginSuccess }: OwnerLoginProps) {
  const [token, setToken] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async () => {
    if (!token.trim()) {
      setError('Please enter your owner token');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const result = await ownerLogin(token);
      
      if (result.success) {
        onLoginSuccess(result);
      } else {
        setError(result.message);
      }
    } catch (err) {
      setError('Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="owner-login-container">
      <div className="owner-login-card">
        <h2>Owner Authentication</h2>
        <p className="owner-login-subtitle">
          Enter your owner token to access the private dashboard
        </p>
        
        <div className="owner-login-form">
          <div className="form-group">
            <label htmlFor="owner-token">Owner Token</label>
            <input
              id="owner-token"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Enter your owner token..."
              className={error ? 'error' : ''}
              onKeyPress={(e) => e.key === 'Enter' && handleLogin()}
            />
            {error && <span className="error-message">{error}</span>}
          </div>
          
          <button
            onClick={handleLogin}
            disabled={loading || !token.trim()}
            className="owner-login-btn"
          >
            {loading ? 'Authenticating...' : 'Access Owner Dashboard'}
          </button>
        </div>
        
        <div className="owner-login-info">
          <h3>Owner Information</h3>
          <p><strong>Name:</strong> Juan Gonzalez</p>
          <p><strong>Email:</strong> sahjonycapitalllc@outlook.com</p>
          <p><strong>Phone:</strong> +16783466284</p>
          <p><strong>Location:</strong> Houston, Texas</p>
        </div>
      </div>

      <style jsx>{`
        .owner-login-container {
          display: flex;
          justify-content: center;
          align-items: center;
          min-height: 100vh;
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          padding: 20px;
        }

        .owner-login-card {
          background: white;
          border-radius: 12px;
          padding: 40px;
          box-shadow: 0 20px 40px rgba(0,0,0,0.1);
          max-width: 400px;
          width: 100%;
        }

        .owner-login-card h2 {
          margin: 0 0 10px 0;
          color: #333;
          font-size: 24px;
          font-weight: 600;
        }

        .owner-login-subtitle {
          color: #666;
          margin-bottom: 30px;
          font-size: 14px;
        }

        .form-group {
          margin-bottom: 20px;
        }

        .form-group label {
          display: block;
          margin-bottom: 5px;
          color: #333;
          font-weight: 500;
        }

        .form-group input {
          width: 100%;
          padding: 12px;
          border: 2px solid #e1e5e9;
          border-radius: 6px;
          font-size: 16px;
          transition: border-color 0.2s;
        }

        .form-group input:focus {
          outline: none;
          border-color: #667eea;
        }

        .form-group input.error {
          border-color: #e74c3c;
        }

        .error-message {
          color: #e74c3c;
          font-size: 14px;
          margin-top: 5px;
          display: block;
        }

        .owner-login-btn {
          width: 100%;
          background: #667eea;
          color: white;
          border: none;
          padding: 12px;
          border-radius: 6px;
          font-size: 16px;
          font-weight: 600;
          cursor: pointer;
          transition: background 0.2s;
        }

        .owner-login-btn:hover:not(:disabled) {
          background: #5a6fd8;
        }

        .owner-login-btn:disabled {
          background: #ccc;
          cursor: not-allowed;
        }

        .owner-login-info {
          margin-top: 30px;
          padding-top: 20px;
          border-top: 1px solid #e1e5e9;
        }

        .owner-login-info h3 {
          margin: 0 0 15px 0;
          color: #333;
          font-size: 18px;
        }

        .owner-login-info p {
          margin: 5px 0;
          color: #666;
          font-size: 14px;
        }
      `}</style>
    </div>
  );
}