import axios from 'axios';

const api = axios.create({
  baseURL: '/admin/api',
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/admin/login';
    }
    return Promise.reject(err);
  }
);

export default api;

export const auth = {
  login: (username: string, password: string) =>
    api.post('/auth/login', { username, password }),
};

export const sslProxy = {
  list: () => api.get('/ssl-proxy/rules'),
  create: (data: any) => api.post('/ssl-proxy/rules', data),
  update: (id: number, data: any) => api.put(`/ssl-proxy/rules/${id}`, data),
  remove: (id: number) => api.delete(`/ssl-proxy/rules/${id}`),
};

export const nftables = {
  list: () => api.get('/nftables/rules'),
  create: (data: any) => api.post('/nftables/rules', data),
  edit: (protocol: string, port: number, old_dest_ip: string, old_dest_port: number, data: any) =>
    api.put(`/nftables/rules/${protocol}/${port}`, data, { params: { old_dest_ip, old_dest_port } }),
  remove: (protocol: string, port: number, dest_ip: string, dest_port: number) =>
    api.delete(`/nftables/rules/${protocol}/${port}`, { params: { dest_ip, dest_port } }),
  updateCnIpset: () => api.post('/nftables/update-cn-ipset'),
};

export const services = {
  status: () => api.get('/services/status'),
  apply: (service: string) => api.post('/services/apply', { service }),
};

export const ports = {
  processes: () => api.get('/ports/processes'),
};

export const system = {
  metrics: () => api.get('/system/metrics'),
  history: () => api.get('/system/metrics/history'),
};
