import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { publicConfig } from '../utils/api';
import type { PublicConfig } from '../types';

const defaultConfig: PublicConfig = {
  icp_number: '',
  site_title: 'DMZ WebUI',
  tab_title: 'DMZ WebUI',
  route_domain: '',
};

const PublicConfigContext = createContext<PublicConfig>(defaultConfig);

export function PublicConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<PublicConfig>(defaultConfig);

  useEffect(() => {
    publicConfig.get()
      .then((response) => {
        setConfig({
          icp_number: response.data.icp_number || '',
          site_title: response.data.site_title || defaultConfig.site_title,
          tab_title: response.data.tab_title || defaultConfig.tab_title,
          route_domain: response.data.route_domain || '',
        });
      })
      .catch(() => setConfig(defaultConfig));
  }, []);

  useEffect(() => {
    document.title = config.tab_title;
  }, [config.tab_title]);

  return (
    <PublicConfigContext.Provider value={config}>
      {children}
    </PublicConfigContext.Provider>
  );
}

export function usePublicConfig() {
  return useContext(PublicConfigContext);
}
