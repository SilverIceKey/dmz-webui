export interface PublicConfig {
  icp_number: string;
  site_title: string;
  tab_title: string;
  route_domain: string;
}

export interface NfRule {
  id: number;
  port: number;
  protocol: string;
  dest_ip: string;
  dest_port: number;
  comment?: string;
  whitelist_type: string;
  whitelist_ips?: string;
}

export interface LocalPortRule {
  id: number;
  port: number;
  protocol: string;
  comment?: string;
  whitelist_type: string;
  whitelist_ips?: string;
}

export interface ServiceStatus {
  name: string;
  active: boolean;
  status: string;
}

export interface PortProcess {
  port: number;
  protocol: string;
  pid?: number;
  command?: string;
  user?: string;
}

export interface SslProxyRule {
  id: number;
  port: number;
  dest_ip: string;
  dest_port: number;
  ssl_enabled: boolean;
  comment?: string;
}

export interface SiteRoute {
  id: number;
  route_type: 'proxy' | 'static';
  hostname: string;
  path: string;
  dest_host?: string;
  dest_port?: number;
  strip_prefix: boolean;
  ssl_enabled: boolean;
  static_directory?: string;
  comment?: string;
}

export interface SniRoute {
  id: number;
  hostname: string;
  dest_host: string;
  dest_port: number;
  comment?: string;
}

export interface SystemMetrics {
  cpu_percent: number;
  memory: {
    total_gb: number;
    used_gb: number;
    percent: number;
  };
  disk: {
    total_gb: number;
    used_gb: number;
    percent: number;
    path: string;
  };
  network: {
    bytes_sent: number;
    bytes_recv: number;
    sent_rate: number;
    recv_rate: number;
  };
  load_average: number[];
  uptime_seconds: number;
  boot_time: number;
}
