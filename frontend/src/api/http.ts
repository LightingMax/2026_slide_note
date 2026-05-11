import axios from 'axios'

export const http = axios.create({
  baseURL: '/api',
  timeout: 120000
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

