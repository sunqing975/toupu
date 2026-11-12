import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom"
import {
  ArrowLeftRight,
  BookText,
  ChartPie,
  LayoutDashboard,
  Settings,
  Tags,
  Upload,
  Wallet,
} from "lucide-react"
import { APP_VERSION } from "./version"
import { Dashboard } from "./pages/Dashboard"
import { Accounts } from "./pages/Accounts"
import { Instruments } from "./pages/Instruments"
import { Placeholder } from "./pages/Placeholder"

const NAV = [
  { to: "/", label: "总览", icon: LayoutDashboard, title: "总览" },
  { to: "/positions", label: "持仓", icon: ChartPie, title: "持仓" },
  { to: "/transactions", label: "交易", icon: ArrowLeftRight, title: "交易" },
  { to: "/ledger", label: "账本", icon: BookText, title: "账本" },
  { to: "/imports", label: "导入", icon: Upload, title: "导入" },
  { to: "/accounts", label: "账户", icon: Wallet, title: "账户" },
  { to: "/instruments", label: "投资品种", icon: Tags, title: "投资品种" },
  { to: "/settings", label: "设置", icon: Settings, title: "设置" },
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
        <Route path="/positions" element={<Placeholder milestone="M2" description="按账户分组的持仓数量与成本" />} />
        <Route path="/transactions" element={<Placeholder milestone="M1" description="交易草稿、确认、入账与冲正" />} />
        <Route path="/ledger" element={<Placeholder milestone="M1" description="复式记账分录流水，只读" />} />
        <Route path="/imports" element={<Placeholder milestone="M4" description="Excel/CSV 导入与期初资产" />} />
        <Route path="/accounts" element={<Accounts />} />
        <Route path="/instruments" element={<Instruments />} />
        <Route path="/settings" element={<Placeholder milestone="M6" description="风险规则、Agent Token 与通知" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
