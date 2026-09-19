import React from 'react';
import {createRoot} from 'react-dom/client';
import '@fontsource-variable/inter';
import 'dockview-react/dist/styles/dockview.css';
import App from './App';
import './style.css';
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
