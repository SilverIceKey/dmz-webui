import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import NftablesPage from './pages/Nftables';
import SslProxyPage from './pages/SslProxy';
import PortsPage from './pages/Ports';
import './App.css';

function App() {
  const isAuth = !!localStorage.getItem('token');

  return (
    <BrowserRouter basename="/admin">
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={isAuth ? <Dashboard /> : <Navigate to="/login" />}
        />
        <Route
          path="/nftables"
          element={isAuth ? <NftablesPage /> : <Navigate to="/login" />}
        />
        <Route
          path="/ssl-proxy"
          element={isAuth ? <SslProxyPage /> : <Navigate to="/login" />}
        />
        <Route
          path="/ports"
          element={isAuth ? <PortsPage /> : <Navigate to="/login" />}
        />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
