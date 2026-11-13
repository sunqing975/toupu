import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom"
import {
  ArrowLeftRight,
  BookText,
  Bot,
  ChartPie,
  Landmark,
  LayoutDashboard,
  LineChart,
  Settings as SettingsIcon,
  ShieldAlert,
  Tags,
  Target,
  Upload,
  Wallet,
} from "lucide-react"
import { APP_VERSION } from "./version"
import { Dashboard } from "./pages/Dashboard"
import { Accounts } from "./pages/Accounts"
import { Instruments } from "./pages/Instruments"
import { Transactions } from "./pages/Transactions"
import { Positions } from "./pages/Positions"
import { Funds } from "./pages/Funds"
import { Imports } from "./pages/Imports"
import { Market } from "./pages/Market"
import { Risk } from "./pages/Risk"
import { Plans } from "./pages/Plans"
import { Ledger } from "./pages/Ledger"
import { Settings } from "./pages/Settings"
import { Agent } from "./pages/Agent"


const NAV = [
  { to: "/", label: "总览", icon: LayoutDashboard, title: "总览" },
  { to: "/positions", label: "持仓", icon: ChartPie, title: "持仓" },
  { to: "/transactions", label: "交易", icon: ArrowLeftRight, title: "交易" },
  { to: "/funds", label: "基金", icon: Landmark, title: "场外基金" },
  { to: "/market", label: "行情", icon: LineChart, title: "行情与收益" },
  { to: "/risk", label: "风险", icon: ShieldAlert, title: "风险" },
  { to: "/plans", label: "计划", icon: Target, title: "计划与提案" },
  { to: "/ledger", label: "账本", icon: BookText, title: "账本" },
  { to: "/imports", label: "导入", icon: Upload, title: "导入" },
  { to: "/accounts", label: "账户", icon: Wallet, title: "账户" },
  { to: "/instruments", label: "投资品种", icon: Tags, title: "投资品种" },
  { to: "/settings", label: "设置", icon: SettingsIcon, title: "设置" },
  { to: "/agent", label: "Agent", icon: Bot, title: "Agent 分析" },
]

function Shell() {
  const { pathname } = useLocation()
  const current = NAV.find((n) => (n.to === "/" ? pathname === "/" : pathname.startsWith(n.to)))

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar__brand">
          <span className="sidebar__brand-mark" aria-hidden>
            投
          </span>
          投谱
        </div>
        <nav className="sidebar__nav" aria-label="主导航">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `sidebar__link${isActive ? " sidebar__link--active" : ""}`}>
              <Icon size={18} aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__version num">投谱 v{APP_VERSION}</div>
      </aside>
      <div className="main">
        <header className="topbar">
          <h1 className="topbar__title">{current?.title ?? ""}</h1>
        </header>
        <Outlet />
      </div>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/positions" element={<Positions />} />
        <Route path="/transactions" element={<Transactions />} />
        <Route path="/funds" element={<Funds />} />
        <Route path="/market" element={<Market />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/plans" element={<Plans />} />
        <Route path="/ledger" element={<Ledger />} />
        <Route path="/imports" element={<Imports />} />
        <Route path="/accounts" element={<Accounts />} />
        <Route path="/instruments" element={<Instruments />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/agent" element={<Agent />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
