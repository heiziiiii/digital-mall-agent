import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API 网关地址
const API_TARGET = 'http://127.0.0.1:8002'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
    // 将网关接口请求代理到后端，规避开发环境跨域
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
})
