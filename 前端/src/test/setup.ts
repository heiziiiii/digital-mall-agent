// Vitest 全局测试初始化：引入 jest-dom 自定义匹配器（toBeInTheDocument 等），
// 并在每个用例后清理已挂载的组件与 localStorage，避免用例间状态串扰。
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
  localStorage.clear()
})
