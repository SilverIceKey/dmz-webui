import { usePublicConfig } from '../context/PublicConfigContext';

export default function NavbarBrand() {
  const { site_title: siteTitle } = usePublicConfig();
  return <div className="navbar-brand">{siteTitle}</div>;
}
