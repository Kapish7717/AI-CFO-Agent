import React, { useState, useEffect, useRef } from 'react';
import { apiJson, apiStream, apiFetch } from './api';

// Custom Markdown Renderer
function renderMarkdown(text) {
  if (!text) return null;
  const lines = text.split('\n');
  let inCodeBlock = false;
  let codeBlockLines = [];
  let inList = false;
  let listItems = [];
  const elements = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith('```')) {
      if (inCodeBlock) {
        elements.push(
          <pre key={`code-${i}`} className="code-block">
            <code>{codeBlockLines.join('\n')}</code>
          </pre>
        );
        codeBlockLines = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockLines.push(line);
      continue;
    }

    if (line.startsWith('- ') || line.startsWith('* ')) {
      inList = true;
      const content = line.substring(2);
      listItems.push(<li key={`li-${i}-${content.substring(0, 5)}`}>{parseInlineMarkdown(content)}</li>);
      continue;
    } else {
      if (inList) {
        elements.push(<ul key={`ul-${i}`}>{listItems}</ul>);
        listItems = [];
        inList = false;
      }
    }

    if (line.startsWith('### ')) {
      elements.push(<h3 key={`h3-${i}`}>{parseInlineMarkdown(line.substring(4))}</h3>);
    } else if (line.startsWith('## ')) {
      elements.push(<h2 key={`h2-${i}`}>{parseInlineMarkdown(line.substring(3))}</h2>);
    } else if (line.startsWith('# ')) {
      elements.push(<h1 key={`h1-${i}`}>{parseInlineMarkdown(line.substring(2))}</h1>);
    } else if (line.trim() === '') {
      continue;
    } else {
      elements.push(<p key={`p-${i}`}>{parseInlineMarkdown(line)}</p>);
    }
  }

  if (inList) {
    elements.push(<ul key={`ul-end`}>{listItems}</ul>);
  }

  return <div className="prose">{elements}</div>;
}

function parseInlineMarkdown(text) {
  const codeSplit = text.split('`');
  if (codeSplit.length > 1) {
    return codeSplit.map((part, index) => {
      if (index % 2 === 1) {
        return <code key={`icode-${index}`}>{part}</code>;
      }
      return parseBoldMarkdown(part);
    });
  }
  return parseBoldMarkdown(text);
}

function parseBoldMarkdown(text) {
  const boldSplit = text.split('**');
  if (boldSplit.length > 1) {
    return boldSplit.map((part, index) => {
      if (index % 2 === 1) {
        return <strong key={`bold-${index}`}>{part}</strong>;
      }
      return part;
    });
  }
  return text;
}

// 1. PREMIUM SVG LINE/AREA CHART
function FinancialOverviewChart({ trendData }) {
  const [hoveredIndex, setHoveredIndex] = useState(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  if (!trendData || trendData.length === 0) {
    return (
      <div className="empty-state" style={{ height: '220px' }}>
        <span className="empty-state-icon">📊</span>
        <p>No financial trend data available</p>
      </div>
    );
  }

  const width = 600;
  const height = 220;
  const padding = { left: 45, right: 15, top: 15, bottom: 30 };

  const activeWidth = width - padding.left - padding.right;
  const activeHeight = height - padding.top - padding.bottom;

  // Track both positive and negative values for dynamic Y-axis floor
  const allValues = [];
  trendData.forEach(d => {
    allValues.push(d.revenue || 0);
    allValues.push(d.expenses || 0);
    allValues.push(d.net_profit || 0);
  });
  
  const minVal = Math.min(...allValues, 0);
  const maxVal = Math.max(...allValues, 100000);
  
  // Clean Y-axis floor and ceiling
  const yFloor = minVal < 0 ? Math.floor(minVal * 1.15 / 100000) * 100000 : 0;
  const yCeil = Math.ceil(maxVal * 1.15 / 100000) * 100000;
  const yRange = yCeil - yFloor;

  const pointsCount = trendData.length;
  const xStep = activeWidth / (pointsCount - 1 || 1);

  const getCoords = (index, val) => {
    const x = padding.left + index * xStep;
    const y = padding.top + activeHeight - ((val - yFloor) / yRange) * activeHeight;
    return { x, y };
  };

  // Build SVG Path strings
  let revPath = '';
  let expPath = '';
  let profPath = '';

  trendData.forEach((d, i) => {
    const coordsRev = getCoords(i, d.revenue || 0);
    const coordsExp = getCoords(i, d.expenses || 0);
    const coordsProf = getCoords(i, d.net_profit || 0);

    if (i === 0) {
      revPath = `M ${coordsRev.x} ${coordsRev.y}`;
      expPath = `M ${coordsExp.x} ${coordsExp.y}`;
      profPath = `M ${coordsProf.x} ${coordsProf.y}`;
    } else {
      revPath += ` L ${coordsRev.x} ${coordsRev.y}`;
      expPath += ` L ${coordsExp.x} ${coordsExp.y}`;
      profPath += ` L ${coordsProf.x} ${coordsProf.y}`;
    }
  });

  // Close area paths for gradient shapes (drop to yFloor position)
  const startX = getCoords(0, yFloor).x;
  const endX = getCoords(pointsCount - 1, yFloor).x;
  const bottomY = padding.top + activeHeight;

  const revAreaPath = `${revPath} L ${endX} ${bottomY} L ${startX} ${bottomY} Z`;
  const expAreaPath = `${expPath} L ${endX} ${bottomY} L ${startX} ${bottomY} Z`;

  const handleMouseMove = (e, index) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setHoveredIndex(index);
    setTooltipPos({ x, y });
  };

  const formatShortCurrency = (val) => {
    const sign = val < 0 ? '-' : '';
    const absVal = Math.abs(val);
    if (absVal >= 1000000) return `${sign}$${(absVal / 1000000).toFixed(1)}M`;
    if (absVal >= 1000) return `${sign}$${(absVal / 1000).toFixed(0)}K`;
    return `${sign}$${absVal}`;
  };

  // Zero baseline line index Y position
  const zeroCoords = getCoords(0, 0);

  return (
    <div className="chart-container-inner" style={{ height: '220px' }} onMouseLeave={() => setHoveredIndex(null)}>
      <svg className="chart-svg" viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <linearGradient id="revGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent-green)" stopOpacity="0.15" />
            <stop offset="100%" stopColor="var(--accent-green)" stopOpacity="0.0" />
          </linearGradient>
          <linearGradient id="expGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent-red)" stopOpacity="0.12" />
            <stop offset="100%" stopColor="var(--accent-red)" stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* Grid lines */}
        {[0, 0.5, 1].map((r, i) => {
          const y = padding.top + activeHeight * (1 - r);
          const gridVal = yFloor + yRange * r;
          return (
            <g key={i}>
              <line className="chart-grid-line" x1={padding.left} y1={y} x2={width - padding.right} y2={y} />
              <text className="chart-label" x={padding.left - 10} y={y + 4} textAnchor="end">
                {formatShortCurrency(gridVal)}
              </text>
            </g>
          );
        })}

        {/* $0 Dotted Baseline separator if there is negative range */}
        {yFloor < 0 && (
          <line 
            x1={padding.left} 
            y1={zeroCoords.y} 
            x2={width - padding.right} 
            y2={zeroCoords.y} 
            stroke="var(--text-muted)" 
            strokeWidth="1.5px" 
            strokeDasharray="3,3" 
            opacity={0.6} 
          />
        )}

        {/* X Axis Date labels */}
        {trendData.map((d, i) => {
          const x = padding.left + i * xStep;
          return (
            <text key={i} className="chart-label" x={x} y={height - padding.bottom + 18} textAnchor="middle">
              {d.date}
            </text>
          );
        })}

        {/* Filled Areas */}
        <path d={revAreaPath} fill="url(#revGradient)" />
        <path d={expAreaPath} fill="url(#expGradient)" />

        {/* Line curves */}
        {pointsCount > 1 && <path className="chart-line-revenue" d={revPath} style={{ strokeWidth: '2.5px' }} />}
        {pointsCount > 1 && <path className="chart-line" d={expPath} style={{ strokeWidth: '2.5px', stroke: 'var(--accent-red)' }} />}
        {pointsCount > 1 && <path className="chart-line-net" d={profPath} style={{ stroke: 'var(--text-primary)', strokeWidth: '2px', strokeDasharray: '3,3', opacity: 0.8 }} />}

        {/* Hover detection nodes */}
        {trendData.map((d, i) => {
          const pExp = getCoords(i, d.expenses || 0);
          const pRev = getCoords(i, d.revenue || 0);
          return (
            <g key={i}>
              <circle
                cx={pExp.x}
                cy={(pExp.y + pRev.y) / 2}
                r={20}
                fill="transparent"
                style={{ cursor: 'pointer' }}
                onMouseMove={(e) => handleMouseMove(e, i)}
              />
              {hoveredIndex === i && (
                <>
                  <circle cx={pRev.x} cy={pRev.y} r={5} fill="var(--accent-green)" />
                  <circle cx={pExp.x} cy={pExp.y} r={5} fill="var(--accent-red)" />
                </>
              )}
            </g>
          );
        })}
      </svg>

      {/* Tooltip Overlay */}
      {hoveredIndex !== null && trendData[hoveredIndex] && (
        <div
          className="tooltip"
          style={{
            left: `${tooltipPos.x}px`,
            top: `${tooltipPos.y}px`,
            backgroundColor: '#18181b',
            border: '1px solid var(--border-color)',
            padding: '0.5rem 0.75rem',
            transform: 'translate(-50%, -110%)'
          }}
        >
          <div style={{ fontWeight: 700, fontSize: '0.8rem', marginBottom: '3px', color: 'white' }}>
            {trendData[hoveredIndex].date}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '0.7rem' }}>
            <span style={{ color: 'var(--accent-green)' }}>Revenue: {new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(trendData[hoveredIndex].revenue)}</span>
            <span style={{ color: 'var(--accent-red)' }}>Expenses: {new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(trendData[hoveredIndex].expenses)}</span>
            <span style={{ color: 'white' }}>Net Profit: {new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(trendData[hoveredIndex].net_profit)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// 2. DONUT CATEGORY CHART
function CategoriesDonutChart({ categories, totalAmountStr }) {
  const [hoveredIndex, setHoveredIndex] = useState(null);

  if (!categories || categories.length === 0) {
    return (
      <div className="empty-state" style={{ padding: '1.5rem 0' }}>
        <span className="empty-state-icon">🍩</span>
        <p>No data</p>
      </div>
    );
  }

  // Predefined color mapping per dataset category
  const categoryColorMap = {
    'Payroll': '#3b82f6',
    'Operations': '#f43f5e',
    'Software': '#a855f7',
    'Marketing': '#f59e0b',
    'R&D': '#10b981',
    'Infrastructure': '#06b6d4',
    'HR': '#ec4899',
    'Travel': '#f97316',
    'Legal': '#6366f1',
    'Others': '#6b7280'
  };

  const sliceColors = [
    '#3b82f6', '#f43f5e', '#f59e0b', '#a855f7', '#10b981',
    '#06b6d4', '#ec4899', '#f97316', '#6366f1', '#6b7280'
  ];

  const getCategoryColor = (catName, idx) => {
    return categoryColorMap[catName] || sliceColors[idx % sliceColors.length];
  };

  // Circumference of radius 38 is 238.76
  const radius = 38;
  const circ = 2 * Math.PI * radius;
  
  let accumulatedPercent = 0;

  return (
    <div className="expense-donut-container">
      <div className="donut-svg-wrap">
        <svg viewBox="0 0 100 100" style={{ transform: 'rotate(-90deg)', width: '100%', height: '100%' }}>
          {categories.map((c, i) => {
            const val = (c.percent / 100) * circ;
            const offset = (accumulatedPercent / 100) * circ;
            accumulatedPercent += c.percent;

            const strokeColor = getCategoryColor(c.category, i);

            return (
              <circle
                key={i}
                cx="50"
                cy="50"
                r={radius}
                fill="none"
                stroke={strokeColor}
                strokeWidth="11"
                strokeDasharray={`${val} ${circ}`}
                strokeDashoffset={-offset}
                style={{
                  transition: 'stroke-width 0.2s',
                  cursor: 'pointer',
                  strokeWidth: hoveredIndex === i ? '14' : '11'
                }}
                onMouseEnter={() => setHoveredIndex(i)}
                onMouseLeave={() => setHoveredIndex(null)}
              />
            );
          })}
        </svg>

        {/* Center label */}
        <div className="donut-center-info">
          <span className="donut-center-val">{totalAmountStr}</span>
          <span className="donut-center-lbl">Total</span>
        </div>
      </div>

      {/* Legend list */}
      <div className="category-legend-list">
        {categories.map((c, i) => {
          const color = getCategoryColor(c.category, i);
          const isHovered = hoveredIndex === i;
          return (
            <div
              key={i}
              className="cat-legend-row"
              style={{
                opacity: hoveredIndex !== null && !isHovered ? 0.4 : 1,
                fontWeight: isHovered ? 700 : 500,
                transition: 'opacity 0.2s'
              }}
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
            >
              <div className="cat-legend-name-wrap">
                <span className="cat-color-box" style={{ backgroundColor: color }} />
                <span style={{ color: 'var(--text-secondary)' }}>{c.category}</span>
              </div>
              <div className="cat-legend-values">
                <span className="cat-legend-val">{c.amount_formatted}</span>
                <span className="cat-legend-pct">{c.percent}%</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// 3. MAIN APP CONTAINER
export default function App() {
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('cfo_user');
    return saved ? JSON.parse(saved) : null;
  });
  const [activeTab, setActiveTab] = useState('dashboard');

  // Auth form states
  const [isRegistering, setIsRegistering] = useState(false);
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authName, setAuthName] = useState('');
  const [authRole, setAuthRole] = useState('Finance Head');
  const [authError, setAuthError] = useState('');

  // Chat/Agent Parameters
  const [expenseFile, setExpenseFile] = useState(null);
  const [expenseFileName, setExpenseFileName] = useState('');
  const [expenseUrl, setExpenseUrl] = useState('');
  const [revenueFile, setRevenueFile] = useState(null);
  const [revenueFileName, setRevenueFileName] = useState('');
  const [revenueUrl, setRevenueUrl] = useState('');

  const [budgetMarketing, setBudgetMarketing] = useState(5000);
  const [budgetOperations, setBudgetOperations] = useState(8000);
  const [budgetTravel, setBudgetTravel] = useState(2000);

  // Email/Meeting schedule inputs
  const [dispatchEmail, setDispatchEmail] = useState(user?.email || '');
  const [meetingTime, setMeetingTime] = useState('');

  // Chat/assistant logs
  const [messages, setMessages] = useState([
    {
      sender: 'agent',
      text: "Hi! 👋 I've analyzed your financial data.\nHow can I help you today?",
      timestamp: new Date().toLocaleTimeString(),
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [agentSteps, setAgentSteps] = useState([]);
  const [pdfAvailable, setPdfAvailable] = useState(false);

  // Dashboard Overview state
  const [dashboardOverview, setDashboardOverview] = useState(null);
  const [selectedMonth, setSelectedMonth] = useState('');
  const [dashLoading, setDashLoading] = useState(false);

  // Auth statuses
  const [authStatus, setAuthStatus] = useState('checking');
  const [authUrl, setAuthUrl] = useState('');
  const [authMsg, setAuthMsg] = useState('');
  const [authAccordionOpen, setAuthAccordionOpen] = useState(false);
  const [showDispatch, setShowDispatch] = useState(false);

  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (user) {
      checkGoogleAuthStatus();
      loadUserSettings();
      loadDashboardOverview('');
      loadChatHistory();
      setDispatchEmail(user.email || '');
    }
  }, [user]);

  const loadChatHistory = async () => {
    if (!user) return;
    try {
      const data = await apiJson(`/api/chat/history?user_id=${user.id}`);
      if (Array.isArray(data)) {
        setMessages(data);
      }
    } catch (e) {
      console.error("Failed to load chat history:", e);
    }
  };

  const loadUserSettings = async () => {
    if (!user) return;
    try {
      const data = await apiJson(`/api/user-settings?user_id=${user.id}`);
      if (data && !data.error) {
        setBudgetMarketing(data.budget_marketing || 5000);
        setBudgetOperations(data.budget_operations || 8000);
        setBudgetTravel(data.budget_travel || 2000);
        if (data.expense_file_name) setExpenseFileName(data.expense_file_name);
        if (data.expense_file_path) setExpenseFile(data.expense_file_path);
        if (data.expense_url) setExpenseUrl(data.expense_url);
        if (data.revenue_file_name) setRevenueFileName(data.revenue_file_name);
        if (data.revenue_file_path) setRevenueFile(data.revenue_file_path);
        if (data.revenue_url) setRevenueUrl(data.revenue_url);
        if (data.selected_month) setSelectedMonth(data.selected_month);
      }
    } catch (e) {
      console.error("Failed to load settings:", e);
    }
  };

  const handleBudgetChange = async (type, val) => {
    let m = budgetMarketing;
    let o = budgetOperations;
    let t = budgetTravel;
    if (type === 'marketing') { setBudgetMarketing(val); m = val; }
    else if (type === 'operations') { setBudgetOperations(val); o = val; }
    else if (type === 'travel') { setBudgetTravel(val); t = val; }

    if (!user) return;
    try {
      await apiJson(`/api/user-settings?user_id=${user.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          budget_marketing: m,
          budget_operations: o,
          budget_travel: t
        })
      });
    } catch (e) {
      console.error("Failed to update budgets in DB:", e);
    }
  };

  const checkGoogleAuthStatus = async () => {
    if (!user) return;
    try {
      const data = await apiJson(`/auth/status?user_id=${user.id}`);
      if (data.authenticated) {
        setAuthStatus('connected');
      } else {
        setAuthStatus('disconnected');
      }
    } catch (e) {
      setAuthStatus('error');
    }
  };

  const getGoogleAuthUrl = async () => {
    if (!user) return;
    try {
      const data = await apiJson(`/auth/url?user_id=${user.id}`);
      setAuthUrl(data.url);
    } catch (e) {
      setAuthMsg('Error retrieving login link.');
    }
  };

  const handleManualAuthExchange = async () => {
    if (!manualCode || !user) return;
    setAuthMsg('Exchanging code...');
    try {
      const data = await apiJson('/auth/exchange', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: manualCode, user_id: user.id }),
      });
      setAuthMsg(data.message);
      checkGoogleAuthStatus();
    } catch (e) {
      setAuthMsg(`Authentication exchange failed: ${e.message || e}`);
    }
  };

  const handleGoogleDisconnect = async () => {
    if (!user) return;
    try {
      await apiJson(`/api/auth/google/disconnect?user_id=${user.id}`, { method: 'POST' });
      setAuthStatus('disconnected');
      setAuthUrl('');
    } catch (e) {
      console.error('Failed to disconnect Google:', e);
      setAuthStatus('disconnected');
      setAuthUrl('');
    }
  };

  const loadDashboardOverview = async (month) => {
    if (!user) return;
    setDashLoading(true);
    try {
      const url = month ? `/api/dashboard/overview?month=${encodeURIComponent(month)}&user_id=${user.id}` : `/api/dashboard/overview?user_id=${user.id}`;
      const data = await apiJson(url);
      if (!data.error) {
        setDashboardOverview(data);
        setSelectedMonth(data.selected_month);
      }
    } catch (e) {
      console.error('Failed to load overview:', e);
    } finally {
      setDashLoading(false);
    }
  };

  const handleMonthChange = async (e) => {
    const month = e.target.value;
    setSelectedMonth(month);
    loadDashboardOverview(month);
    if (user) {
      try {
        await apiJson(`/api/user-settings?user_id=${user.id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ selected_month: month }),
        });
      } catch (err) {
        console.error('Failed to save selected month:', err);
      }
    }
  };

  // File Upload Handlers
  const handleFileUpload = async (e, type) => {
    if (!user) return;
    const file = e.target.files[0];
    if (!file) return;

    if (type === 'expense') {
      setExpenseFileName('Uploading...');
    } else {
      setRevenueFileName('Uploading...');
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
      const data = await apiJson(`/api/upload?user_id=${user.id}&file_type=${type}`, {
        method: 'POST',
        body: formData,
      });
      if (data.file_path) {
        if (type === 'expense') {
          setExpenseFile(data.file_path);
          setExpenseFileName(file.name);
        } else {
          setRevenueFile(data.file_path);
          setRevenueFileName(file.name);
        }
        // File path is persisted to user settings on the backend
      } else {
        alert(data.error || 'Upload failed');
        if (type === 'expense') setExpenseFileName('');
        else setRevenueFileName('');
      }
    } catch (err) {
      alert(`Upload error: ${err}`);
      if (type === 'expense') setExpenseFileName('');
      else setRevenueFileName('');
    }
  };

  // SEND SSE MESSAGE
  const handleSendMessage = async (e, customText = null) => {
    if (e) e.preventDefault();
    const promptToSend = (customText || inputText).trim();
    if (!promptToSend || isStreaming || !user) return;

    setInputText('');

    // Append user message
    setMessages(prev => [
      ...prev,
      { sender: 'user', text: promptToSend, timestamp: new Date().toLocaleTimeString() },
    ]);

    // Initial agent placeholder
    setMessages(prev => [
      ...prev,
      { sender: 'agent', text: '🧠 **Agent is thinking...**', timestamp: new Date().toLocaleTimeString() },
    ]);

    setIsStreaming(true);

    // Initializing execution steps
    setAgentSteps([
      { name: 'Google Authentication', status: 'running' },
      { name: 'Data Ingestion', status: 'pending' },
      { name: 'Anomaly Detection', status: 'pending' },
      { name: 'CFO Report Generation', status: 'pending' },
      { name: 'Email Report Dispatch', status: 'pending' },
    ]);

    // Construct full prompt context
    let fullPrompt = promptToSend;
    fullPrompt += `\n\nBUDGET_LIMITS:\n- Marketing: $${budgetMarketing}\n- Operations: $${budgetOperations}\n- Travel: $${budgetTravel}`;

    if (expenseFile) {
      fullPrompt += `\n\nEXPENSE_FILE_PATH: ${expenseFile}`;
    } else if (expenseUrl) {
      fullPrompt += `\n\nEXPENSE_SHEET_URL: ${expenseUrl}`;
    }

    if (revenueFile) {
      fullPrompt += `\n\nREVENUE_FILE_PATH: ${revenueFile}`;
    } else if (revenueUrl) {
      fullPrompt += `\n\nREVENUE_SHEET_URL: ${revenueUrl}`;
    }

    try {
      const streamBody = await apiStream('/stream', { prompt: fullPrompt, user_id: user.id });
      const reader = streamBody.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let botMessage = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');

        buffer = lines.pop();

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.substring(6).trim();
            if (!dataStr) continue;

            try {
              const data = JSON.parse(dataStr);
              const stepName = data.step;
              const msgContent = data.message;

              if (data.error) {
                botMessage += `\n\n❌ **Error during execution:** ${data.error}`;
                setMessages(prev => {
                  const copy = [...prev];
                  copy[copy.length - 1].text = botMessage;
                  return copy;
                });
                break;
              }

              // Update checklist
              if (stepName === 'tools') {
                if (msgContent && (msgContent.includes('Success') || msgContent.includes('Successfully') || msgContent.includes('complete'))) {
                  let stepIdx = -1;
                  if (msgContent.includes('Authenticated') || msgContent.includes('credentials')) stepIdx = 0;
                  else if (msgContent.includes('Loaded') || msgContent.includes('Unified')) stepIdx = 1;
                  else if (msgContent.includes('Anomaly') || msgContent.includes('breaches')) stepIdx = 2;
                  else if (msgContent.includes('PDF') || msgContent.includes('report') || msgContent.includes('executive_cfo_report')) stepIdx = 3;
                  else if (msgContent.includes('Email') || msgContent.includes('sent')) stepIdx = 4;

                  if (stepIdx !== -1) {
                     setAgentSteps(prev => {
                      const copy = [...prev];
                      copy[stepIdx].status = 'success';
                      for (let k = 0; k < copy.length; k++) {
                        if (copy[k].status === 'pending') {
                          copy[k].status = 'running';
                          break;
                        }
                      }
                      return copy;
                    });
                  }
                }
              }

              if (stepName === 'agent' && msgContent) {
                botMessage = msgContent;
                setMessages(prev => {
                  const copy = [...prev];
                  copy[copy.length - 1].text = botMessage;
                  return copy;
                });
              }
            } catch (err) {
              // Ignore line parsing
            }
          }
        }
      }

      setIsStreaming(false);
      setAgentSteps(prev => prev.map(s => s.status === 'running' ? { ...s, status: 'success' } : s));

      // Refresh overview data
      loadDashboardOverview(selectedMonth);
      checkReportAvailability();

    } catch (e) {
      setMessages(prev => {
        const copy = [...prev];
        copy[copy.length - 1].text = `❌ **Connection Error:** ${e.message}\n\nEnsure backend is running.`;
        return copy;
      });
      setIsStreaming(false);
      setAgentSteps(prev => prev.map(s => s.status === 'running' ? { ...s, status: 'error' } : s));
    }
  };

  const checkReportAvailability = async () => {
    if (!user) return;
    try {
      const res = await apiFetch(`/api/download-report?user_id=${user.id}`);
      if (res.ok) {
        const contentType = res.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
          setPdfAvailable(false);
        } else {
          setPdfAvailable(true);
        }
      } else {
        setPdfAvailable(false);
      }
    } catch (e) {
      setPdfAvailable(false);
    }
  };

  const handleRunAgent = (e) => {
    if (e) e.preventDefault();
    const targetEmail = dispatchEmail.trim() || user?.email || '';
    if (!targetEmail) {
      alert('Please enter a recipient email address.');
      return;
    }
    let promptText = `Please generate the CFO report and email it to ${targetEmail}`;
    if (meetingTime) {
      const startObj = new Date(meetingTime);
      const endObj = new Date(startObj.getTime() + 60 * 60 * 1000); // 1 hour meeting default
      
      const formatIsoNoTz = (date) => {
        const pad = (num) => String(num).padStart(2, '0');
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
      };
      
      const startStr = formatIsoNoTz(startObj);
      const endStr = formatIsoNoTz(endObj);
      promptText += `, and schedule a review meeting with ${targetEmail} starting at ${startStr} and ending at ${endStr}`;
    } else {
      promptText += `. Do not schedule a meeting.`;
    }
    handleSendMessage(null, promptText);
  };

  const handleAuthSubmit = async (e) => {
    e.preventDefault();
    setAuthError('');
    const endpoint = isRegistering ? '/api/auth/register' : '/api/auth/login';
    const payload = isRegistering 
      ? { email: authEmail, password: authPassword, full_name: authName, role: authRole }
      : { email: authEmail, password: authPassword };
    
    try {
      const data = await apiJson(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (isRegistering) {
        setIsRegistering(false);
        setAuthPassword('');
        setAuthError('Registration successful! Please log in.');
      } else {
        localStorage.setItem('cfo_user', JSON.stringify(data.user));
        setUser(data.user);
      }
    } catch (err) {
      setAuthError(err.message || 'Connection failed. Please check if backend is running.');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('cfo_user');
    setUser(null);
    setExpenseFile(null);
    setExpenseFileName('');
    setExpenseUrl('');
    setRevenueFile(null);
    setRevenueFileName('');
    setRevenueUrl('');
    setDashboardOverview(null);
    setMessages([
      {
        sender: 'agent',
        text: "Hi! 👋 I've initialized your workspace.\nHow can I help you today?",
        timestamp: new Date().toLocaleTimeString(),
      }
    ]);
  };

  useEffect(() => {
    checkReportAvailability();
  }, [activeTab]);

  // LOGIN SCREEN
  if (!user) {
    return (
      <div className="login-screen-container">
        {/* Animated ambient glow blobs */}
        <div className="login-bg-glow-1" />
        <div className="login-bg-glow-2" />
        
        {/* Subtle grid backdrop */}
        <div className="login-grid-overlay" />
        
        <div className="login-card">
          <div style={{ textAlign: 'center' }}>
            <div className="login-logo-container">
              <div className="login-logo-glow" />
              <svg style={{ width: '28px', height: '28px', fill: 'none', stroke: 'white', strokeWidth: '2.2' }} viewBox="0 0 24 24">
                <path d="M12 2L2 7l10 5 10-5-10-5z" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M2 17l10 5 10-5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M2 12l10 5 10-5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h1 className="login-title">AI CFO Co-Pilot</h1>
            <p className="login-subtitle">Secure Enterprise Financial Intelligence</p>
          </div>

          <form onSubmit={handleAuthSubmit} className="login-form">
            {isRegistering && (
              <>
                <div className="login-field">
                  <label className="login-label">Full Name</label>
                  <div className="login-input-wrap">
                    <input
                      type="text"
                      required
                      className="login-input"
                      placeholder="e.g. Arjun Mehta"
                      value={authName}
                      onChange={(e) => setAuthName(e.target.value)}
                    />
                    <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                      <circle cx="12" cy="7" r="4" />
                    </svg>
                  </div>
                </div>
                <div className="login-field">
                  <label className="login-label">Corporate Role</label>
                  <div className="login-input-wrap">
                    <input
                      type="text"
                      required
                      className="login-input"
                      placeholder="e.g. Finance Head"
                      value={authRole}
                      onChange={(e) => setAuthRole(e.target.value)}
                    />
                    <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
                      <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
                    </svg>
                  </div>
                </div>
              </>
            )}

            <div className="login-field">
              <label className="login-label">Work Email</label>
              <div className="login-input-wrap">
                <input
                  type="email"
                  required
                  className="login-input"
                  placeholder="you@company.com"
                  value={authEmail}
                  onChange={(e) => setAuthEmail(e.target.value)}
                />
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
              </div>
            </div>

            <div className="login-field">
              <label className="login-label">Password</label>
              <div className="login-input-wrap">
                <input
                  type="password"
                  required
                  className="login-input"
                  placeholder="••••••••"
                  value={authPassword}
                  onChange={(e) => setAuthPassword(e.target.value)}
                />
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
              </div>
            </div>

            {authError && (
              <div className={`login-error-alert ${authError.toLowerCase().includes('successful') ? 'success' : 'error'}`}>
                {authError}
              </div>
            )}

            <button type="submit" className="login-btn">
              {isRegistering ? 'Create Account' : 'Sign In to Dashboard'}
            </button>
          </form>

          <div style={{ textAlign: 'center', marginTop: '1.75rem' }}>
            <button
              type="button"
              onClick={() => {
                setIsRegistering(!isRegistering);
                setAuthError('');
              }}
              className="login-footer-btn"
            >
              {isRegistering ? 'Already have an account? Sign In' : "New to AI CFO? Create an account"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* 1. LEFT SIDEBAR NAVIGATION */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <svg className="brand-icon-svg" viewBox="0 0 24 24">
            <path d="M3 3v18h18" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M18.5 7.5L14 12l-3.5-3.5L7 12.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className="brand-info">
            <span className="brand-title">AI CFO Agent</span>
            <span className="brand-subtitle">Your Financial Co-Pilot</span>
          </div>
        </div>

        <div className="sidebar-section">
          <h4 className="sidebar-section-title">Analytics</h4>
          <ul className="sidebar-menu-list">
            <li className={`sidebar-menu-item ${activeTab === 'dashboard' ? 'active' : ''}`}>
              <button onClick={() => setActiveTab('dashboard')}>
                <svg className="sidebar-menu-icon" viewBox="0 0 24 24">
                  <rect x="3" y="3" width="7" height="9" rx="1" strokeLinecap="round" strokeLinejoin="round" />
                  <rect x="14" y="3" width="7" height="5" rx="1" strokeLinecap="round" strokeLinejoin="round" />
                  <rect x="14" y="12" width="7" height="9" rx="1" strokeLinecap="round" strokeLinejoin="round" />
                  <rect x="3" y="16" width="7" height="5" rx="1" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Dashboard
              </button>
            </li>
            <li className="sidebar-menu-item">
              <button onClick={() => alert('Feature coming soon in this mockup')}>
                <svg className="sidebar-menu-icon" viewBox="0 0 24 24">
                  <path d="M21.21 15.89A10 10 0 1 1 8 2.83" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M22 12A10 10 0 0 0 12 2v10z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Financial Overview
              </button>
            </li>
            <li className="sidebar-menu-item">
              <button onClick={() => alert('Feature coming soon in this mockup')}>
                <svg className="sidebar-menu-icon" viewBox="0 0 24 24">
                  <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Cash Flow
              </button>
            </li>
            <li className="sidebar-menu-item">
              <button onClick={() => alert('Feature coming soon in this mockup')}>
                <svg className="sidebar-menu-icon" viewBox="0 0 24 24">
                  <path d="M18 20V10M12 20V4M6 20v-6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Profitability
              </button>
            </li>
            <li className="sidebar-menu-item">
              <button onClick={() => alert('Feature coming soon in this mockup')}>
                <svg className="sidebar-menu-icon" viewBox="0 0 24 24">
                  <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zm20 0h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Forecasting
              </button>
            </li>
            <li className="sidebar-menu-item">
              <button onClick={() => alert('Feature coming soon in this mockup')}>
                <svg className="sidebar-menu-icon" viewBox="0 0 24 24">
                  <rect x="3" y="4" width="18" height="18" rx="2" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M16 2v4M8 2v4M3 10h18" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Budgeting
              </button>
            </li>
          </ul>
        </div>

        <div className="sidebar-section">
          <h4 className="sidebar-section-title">Data</h4>
          <ul className="sidebar-menu-list">
            <li className={`sidebar-menu-item ${activeTab === 'upload' ? 'active' : ''}`}>
              <button onClick={() => setActiveTab('upload')}>
                <svg className="sidebar-menu-icon" viewBox="0 0 24 24">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Upload Data
              </button>
            </li>
            <li className={`sidebar-menu-item ${activeTab === 'auth' ? 'active' : ''}`}>
              <button onClick={() => setActiveTab('auth')}>
                <svg className="sidebar-menu-icon" viewBox="0 0 24 24">
                  <rect x="3" y="11" width="18" height="11" rx="2" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Integrations / Auth
              </button>
            </li>
          </ul>
        </div>

        {/* User Headshot Profile widget with Logout */}
        <div className="sidebar-profile" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', alignItems: 'stretch' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <img className="profile-avatar" src={user.avatar_url || `https://ui-avatars.com/api/?name=${encodeURIComponent(user.full_name || 'User')}&background=4f46e5&color=fff`} alt={user.full_name} />
            <div className="profile-info">
              <span className="profile-name">{user.full_name}</span>
              <span className="profile-role">{user.role}</span>
            </div>
          </div>
          <button 
            onClick={handleLogout}
            style={{
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.2)',
              borderRadius: '6px',
              color: '#ef4444',
              padding: '0.35rem',
              fontSize: '0.75rem',
              fontWeight: 700,
              cursor: 'pointer',
              marginTop: '0.5rem',
              textAlign: 'center',
              display: 'block',
              width: '100%',
              transition: 'background 0.2s'
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(239, 68, 68, 0.2)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'}
          >
            Sign Out 📯
          </button>
        </div>
      </aside>

      {/* 2. RIGHT MAIN VIEWPORT */}
      <div className="main-wrapper">
        <header className="dashboard-header">
          <div className="welcome-info">
            <h2>Welcome back, {user.full_name.split(' ')[0]} 👋</h2>
            <p>Here's what's happening with your business today.</p>
          </div>

          <div className="header-toolbar">
            {/* Months Dropdown selection */}
            {dashboardOverview?.available_months && (
              <select
                className="dropdown-input"
                value={selectedMonth}
                onChange={handleMonthChange}
              >
                {dashboardOverview.available_months.map((m, i) => (
                  <option key={i} value={m}>{m}</option>
                ))}
              </select>
            )}

            {/* Date range string dynamic label */}
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
              {dashboardOverview?.date_range_label || 'Date Range'}
            </span>

            {/* Ingestion redirect */}
            <button className="btn btn-secondary" onClick={() => setActiveTab('upload')} style={{ padding: '0.45rem 1rem', fontSize: '0.8rem' }}>
              📥 Ingest Data
            </button>

            {/* Notification bell widget */}
            <div className="notification-bell">
              <span style={{ fontSize: '1.05rem' }}>🔔</span>
              <span className="notification-badge">3</span>
            </div>
          </div>
        </header>

        {/* View switching logic */}
        {activeTab === 'dashboard' && (
          <div className="content-body">
            {/* Stepper Pipeline visualizer in Dashboard when streaming */}
            {isStreaming && (
              <div className="steps-panel-dashboard">
                <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-color)', marginBottom: '0.5rem' }}>
                  ⏳ Agent Orchestration Running...
                </div>
                <div className="steps-list-horizontal">
                  {agentSteps.map((step, idx) => (
                    <div key={idx} className="step-item-horizontal">
                      <span className={`step-icon ${step.status}`} style={{ width: '14px', height: '14px', fontSize: '0.55rem' }}>
                        {step.status === 'success' && '✓'}
                        {step.status === 'running' && '⏳'}
                        {step.status === 'pending' && '○'}
                        {step.status === 'error' && '✗'}
                      </span>
                      <span>{step.name}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 4 CARDS METRICS ROW */}
            <div className="metrics-row">
              <div className="metric-card">
                <div className="metric-header">
                  <div className="metric-icon-wrap rev">📈</div>
                  <span className="metric-label">Total Revenue</span>
                </div>
                <span className="metric-val">{dashboardOverview?.total_revenue || '$0.00'}</span>
                <span className={`metric-trend ${dashboardOverview?.revenue_trend?.color || 'green'}`}>
                  {dashboardOverview?.revenue_trend?.text || '0%'}
                </span>
              </div>

              <div className="metric-card">
                <div className="metric-header">
                  <div className="metric-icon-wrap exp">📉</div>
                  <span className="metric-label">Total Expenses</span>
                </div>
                <span className="metric-val">{dashboardOverview?.total_expenses || '$0.00'}</span>
                <span className={`metric-trend ${dashboardOverview?.expense_trend?.color || 'red'}`}>
                  {dashboardOverview?.expense_trend?.text || '0%'}
                </span>
              </div>

              <div className="metric-card">
                <div className="metric-header">
                  <div className="metric-icon-wrap prof">💰</div>
                  <span className="metric-label">Net Profit</span>
                </div>
                <span className="metric-val">{dashboardOverview?.net_profit || '$0.00'}</span>
                <span className={`metric-trend ${dashboardOverview?.profit_trend?.color || 'green'}`}>
                  {dashboardOverview?.profit_trend?.text || '0%'}
                </span>
              </div>

              <div className="metric-card">
                <div className="metric-header">
                  <div className="metric-icon-wrap cash">🏦</div>
                  <span className="metric-label">Cash Balance</span>
                </div>
                <span className="metric-val">{dashboardOverview?.cash_balance || '$0.00'}</span>
                <span className={`metric-trend ${dashboardOverview?.cash_trend?.color || 'green'}`}>
                  {dashboardOverview?.cash_trend?.text || '0%'}
                </span>
              </div>
            </div>

            {/* MIDDLE ROW (LINE CHART + CIRCLE GAUGE + CHAT ASSISTANT) */}
            <div className="middle-grid">
              {/* Financial Overview Line/Area Chart */}
              <div className="dashboard-card">
                <div className="card-header-inner">
                  <span className="card-title-main">Financial Overview</span>
                  <div className="line-chart-legend">
                    <div className="legend-dot-item">
                      <span className="dot-indicator rev" />
                      <span>Revenue</span>
                    </div>
                    <div className="legend-dot-item">
                      <span className="dot-indicator exp" />
                      <span>Expenses</span>
                    </div>
                    <div className="legend-dot-item">
                      <span className="dot-indicator prof" style={{ backgroundColor: 'var(--text-primary)' }} />
                      <span>Net Profit</span>
                    </div>
                  </div>
                </div>
                <FinancialOverviewChart trendData={dashboardOverview?.trend_data} />
              </div>

              {/* Profit Margin circular gauge */}
              <div className="dashboard-card" style={{ alignItems: 'center' }}>
                <span className="card-title-main" style={{ alignSelf: 'flex-start' }}>Profit Margin</span>
                <div className="margin-gauge-container">
                  <div className="gauge-svg-wrap">
                    <svg className="gauge-svg" viewBox="0 0 100 100">
                      <circle className="gauge-bg-circle" cx="50" cy="50" r="40" />
                      <circle
                         className="gauge-fill-circle"
                        cx="50"
                        cy="50"
                        r="40"
                        style={{
                          strokeDasharray: '251.2',
                          strokeDashoffset: 251.2 - (dashboardOverview?.profit_margin || 0) / 100 * 251.2
                        }}
                      />
                    </svg>
                    <span className="gauge-text-center">{dashboardOverview?.profit_margin || '0'}%</span>
                  </div>
                  <span className={`metric-trend ${dashboardOverview?.profit_margin_trend?.color || 'green'}`} style={{ fontSize: '0.85rem' }}>
                    {dashboardOverview?.profit_margin_trend?.text || '0%'}
                  </span>
                  <span className="gauge-caption">
                    Your profit margin is {dashboardOverview?.profit_margin_trend?.is_positive ? 'higher' : 'lower'} than last month.
                  </span>
                </div>
              </div>

              {/* AI CFO Assistant Panel */}
              <div className="dashboard-card assistant-panel">
                <div className="assistant-title">
                  <span className="card-title-main">AI CFO Assistant</span>
                  <span style={{ fontSize: '0.95rem' }}>✨</span>
                </div>

                <div className="assistant-message-log">
                  {messages.map((msg, i) => (
                    <div key={i} className={`chat-bubble-panel ${msg.sender}`}>
                      {renderMarkdown(msg.text)}
                    </div>
                  ))}
                  <div ref={chatEndRef} />
                </div>

                {/* AGENT RUN CONTROLS (EMAIL, SCHEDULE MEETING & RUN AGENT BUTTON) */}
                <form className="agent-run-form" onSubmit={handleRunAgent}>
                  <div className="dispatch-fields">
                    <div className="dispatch-field">
                      <label className="dispatch-label">Recipient Email Address</label>
                      <input
                        type="email"
                        className="dispatch-input"
                        placeholder="e.g. client@company.com"
                        value={dispatchEmail}
                        onChange={(e) => setDispatchEmail(e.target.value)}
                        disabled={isStreaming}
                      />
                    </div>
                    <div className="dispatch-field">
                      <label className="dispatch-label">Schedule Meeting Time (Optional)</label>
                      <input
                        type="datetime-local"
                        className="dispatch-input"
                        value={meetingTime}
                        onChange={(e) => setMeetingTime(e.target.value)}
                        disabled={isStreaming}
                      />
                    </div>
                  </div>
                  <button
                    type="submit"
                    className="dispatch-submit-btn"
                    disabled={isStreaming}
                    style={{ marginTop: '0.4rem', height: '40px' }}
                  >
                    {isStreaming ? '🧠 Running Agent...' : '🚀 Run Agent'}
                  </button>
                </form>
              </div>
            </div>

            {/* BOTTOM ROW (DONUT PIE CHART + CASHFLOW SUMMARY + RECENT INSIGHTS) */}
            <div className="bottom-grid">
              {/* Top Expense Categories Donut */}
              <div className="dashboard-card">
                <span className="card-title-main" style={{ marginBottom: '1.25rem' }}>Top Expense Categories</span>
                <CategoriesDonutChart
                  categories={dashboardOverview?.categories}
                  totalAmountStr={dashboardOverview?.total_expenses || '$0.00'}
                />
              </div>

              {/* Cash Flow Summary */}
              <div className="dashboard-card">
                <span className="card-title-main" style={{ marginBottom: '1.25rem' }}>Cash Flow Summary</span>
                <div className="cashflow-summary-list">
                  <div className="cashflow-summary-row">
                    <div className="cf-label-wrap">
                      <span className="cf-arrow in">↓</span>
                      <span>Cash Inflow</span>
                    </div>
                    <span className="cf-value green">{dashboardOverview?.cash_inflow || '$0.00'}</span>
                  </div>

                  <div className="cashflow-summary-row">
                    <div className="cf-label-wrap">
                      <span className="cf-arrow out">↑</span>
                      <span>Cash Outflow</span>
                    </div>
                    <span className="cf-value red">{dashboardOverview?.cash_outflow || '$0.00'}</span>
                  </div>

                  <div className="cashflow-summary-row">
                    <div className="cf-label-wrap">
                      <span className="cf-arrow net">⇄</span>
                      <span>Net Cash Flow</span>
                    </div>
                    <span className="cf-value green">{dashboardOverview?.net_cash_flow || '$0.00'}</span>
                  </div>
                </div>
              </div>

              {/* Recent Insights */}
              <div className="dashboard-card">
                <span className="card-title-main" style={{ marginBottom: '1.25rem' }}>Recent Insights</span>
                <div className="insights-card-content">
                  {dashboardOverview?.recent_insights && dashboardOverview.recent_insights.map((ins, i) => (
                    <div key={i} className="insight-bullet-item">
                      <span className="insight-bulb-icon">💡</span>
                      <span>{ins}</span>
                    </div>
                  ))}
                  <a href="#view-all" className="insights-link" onClick={() => alert('Insights list is dynamic and synced to selected month')}>
                    View All Insights →
                  </a>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 3. INGESTION DATA SOURCE VIEW */}
        {activeTab === 'upload' && (
          <div className="content-body">
            <h2 style={{ fontFamily: 'var(--font-title)', fontWeight: 800, fontSize: '1.5rem', marginBottom: '0.5rem' }}> Ingestion Control Center</h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
              Configure ingestion paths (local file uploads or Google Sheets link) and update target budget limits.
            </p>

            <div className="settings-grid">
              <div className="dashboard-card">
                <h3 className="sidebar-title" style={{ border: 'none', marginBottom: '1rem' }}>Inbound Sources</h3>

                {/* Expense upload */}
                <div className="form-group">
                  <label>Upload Expense File (CSV)</label>
                  <div className="file-upload-container" onClick={() => document.getElementById('exp-input-sett').click()}>
                    <input
                      id="exp-input-sett"
                      type="file"
                      accept=".csv"
                      style={{ display: 'none' }}
                      onChange={(e) => handleFileUpload(e, 'expense')}
                    />
                    <div className="file-upload-icon">📥</div>
                    {expenseFileName ? (
                      <span className="file-upload-name">{expenseFileName}</span>
                    ) : (
                      <span className="file-upload-text">Click to browse file</span>
                    )}
                  </div>
                </div>

                <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.75rem', margin: '0.5rem 0' }}>— OR —</div>

                <div className="form-group">
                  <label>Expense Google Sheets URL</label>
                  <input
                    type="text"
                    placeholder="https://docs.google.com/spreadsheets/d/..."
                    value={expenseUrl}
                    onChange={(e) => {
                      setExpenseUrl(e.target.value);
                      if (user) {
                        apiJson(`/api/user-settings?user_id=${user.id}`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ expense_url: e.target.value })
                        }).catch((err) => console.error('Failed to save expense URL:', err));
                      }
                    }}
                  />
                </div>

                <div className="divider" style={{ margin: '1.5rem 0' }} />

                {/* Revenue upload */}
                <div className="form-group">
                  <label>Upload Revenue File (CSV)</label>
                  <div className="file-upload-container" onClick={() => document.getElementById('rev-input-sett').click()}>
                    <input
                      id="rev-input-sett"
                      type="file"
                      accept=".csv"
                      style={{ display: 'none' }}
                      onChange={(e) => handleFileUpload(e, 'revenue')}
                    />
                    <div className="file-upload-icon">📥</div>
                    {revenueFileName ? (
                      <span className="file-upload-name">{revenueFileName}</span>
                    ) : (
                      <span className="file-upload-text">Click to browse file</span>
                    )}
                  </div>
                </div>

                <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.75rem', margin: '0.5rem 0' }}>— OR —</div>

                <div className="form-group">
                  <label>Revenue Google Sheets URL</label>
                  <input
                    type="text"
                    placeholder="https://docs.google.com/spreadsheets/d/..."
                    value={revenueUrl}
                    onChange={(e) => {
                      setRevenueUrl(e.target.value);
                      if (user) {
                        apiJson(`/api/user-settings?user_id=${user.id}`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ revenue_url: e.target.value })
                        }).catch((err) => console.error('Failed to save revenue URL:', err));
                      }
                    }}
                  />
                </div>
              </div>

              {/* Budget Limits card & download link */}
              <div className="dashboard-card" style={{ gap: '1.25rem' }}>
                <div>
                  <h3 className="sidebar-title" style={{ border: 'none', marginBottom: '1rem' }}>Operating Budgets Limits</h3>
                  <div className="form-group">
                    <label>Marketing Budgets ($)</label>
                    <input
                      type="number"
                      value={budgetMarketing}
                      onChange={(e) => handleBudgetChange('marketing', Number(e.target.value))}
                    />
                  </div>
                  <div className="form-group">
                    <label>Operations Budgets ($)</label>
                    <input
                      type="number"
                      value={budgetOperations}
                      onChange={(e) => handleBudgetChange('operations', Number(e.target.value))}
                    />
                  </div>
                  <div className="form-group">
                    <label>Travel Budgets ($)</label>
                    <input
                      type="number"
                      value={budgetTravel}
                      onChange={(e) => handleBudgetChange('travel', Number(e.target.value))}
                    />
                  </div>
                </div>

                <div className="divider" />

                <div>
                  <h3 className="sidebar-title" style={{ border: 'none', marginBottom: '0.5rem' }}>Download Reports</h3>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                    Retrieve compiled PDF reports after running anomaly sweeps.
                  </p>
                  <button
                    className="btn btn-primary btn-full"
                    disabled={!pdfAvailable}
                    onClick={() => window.open(`/api/download-report?user_id=${user.id}`, '_blank')}
                  >
                    📄 {pdfAvailable ? 'Download CFO PDF Report' : 'PDF Report Not Generated Yet'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 4. INTEGRATIONS AND GOOGLE AUTH VIEW */}
        {activeTab === 'auth' && (
          <div className="content-body" style={{ alignItems: 'center', justifyContent: 'center', flex: 1 }}>
            <div className="dashboard-card auth-card" style={{ maxWidth: '600px', width: '100%', gap: '1.25rem', textAlign: 'center', padding: '2rem' }}>
              {authStatus === 'connected' ? (
                <>
                  <div className="auth-status-icon connected" style={{ width: '60px', height: '60px', fontSize: '1.8rem' }}>✓</div>
                  <h2 className="auth-status-text">Google Account Synced</h2>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                    Access permissions are connected. The AI CFO Assistant is authorized to use Gmail tools, Calendar schedules, and Sheets readers securely.
                  </p>
                  <button className="btn btn-secondary" onClick={handleGoogleDisconnect}>
                    Disconnect Google Session
                  </button>
                </>
              ) : (
                <>
                  <div className="auth-status-icon disconnected" style={{ width: '60px', height: '60px', fontSize: '1.8rem' }}>✗</div>
                  <h2 className="auth-status-text">OAuth Credentials Missing</h2>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                    Link your account to configure automated calendar events, schedule anomaly reviews, and dispatch PDF files directly.
                  </p>
                  <button className="btn btn-primary" onClick={getGoogleAuthUrl}>
                    Connect Google Services 🔗
                  </button>

                  {authUrl && (
                    <div style={{ marginTop: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.75rem', width: '100%' }}>
                      <a
                        href={authUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-secondary"
                        style={{ display: 'inline-block', textDecoration: 'none', backgroundColor: 'var(--accent-glow)', color: 'var(--accent-color)', fontWeight: 700 }}
                      >
                        Launch OAuth Sign-In
                      </a>
                    </div>
                  )}

                  {/* Manual fallback */}
                  <div className="accordion" style={{ marginTop: '1.5rem', width: '100%' }}>
                    <div
                      className="accordion-header"
                      onClick={() => setAuthAccordionOpen(!authAccordionOpen)}
                      style={{ padding: '0.6rem 1rem', fontSize: '0.8rem' }}
                    >
                      <span>Manual Callback Sync</span>
                      <span>{authAccordionOpen ? '▲' : '▼'}</span>
                    </div>

                    {authAccordionOpen && (
                      <div className="accordion-content" style={{ padding: '1rem', gap: '0.75rem' }}>
                        <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textAlign: 'left' }}>
                          Paste the authorization code query argument from the address bar below.
                        </p>
                        <div className="form-group" style={{ textAlign: 'left' }}>
                          <label>Code Parameter</label>
                          <input
                            type="text"
                            placeholder="E.g. 4/0AdkVLPy..."
                            value={manualCode}
                            onChange={(e) => setManualCode(e.target.value)}
                          />
                        </div>
                        <button className="btn btn-secondary btn-full" style={{ padding: '0.5rem' }} onClick={handleManualAuthExchange}>
                          Sync Callback Session
                        </button>
                        {authMsg && (
                          <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-color)' }}>
                            {authMsg}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

