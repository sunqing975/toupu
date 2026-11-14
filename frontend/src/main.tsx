import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "./App"
import { ToastProvider } from "./components/Toast"
// 自托管变量字体：Geist 负责西文/数字，中文字形回退到系统字体（PingFang SC 等）
import "@fontsource-variable/geist/wght.css"
import "@fontsource-variable/geist-mono/wght.css"
import "./styles/tokens.css"
import "./styles/global.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <App />
      </ToastProvider>
    </BrowserRouter>
  </StrictMode>,
)
