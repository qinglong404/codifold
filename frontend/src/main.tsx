import React from 'react';
import ReactDOM from 'react-dom/client';
import {ReactFlowProvider} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './app.css';
import './blocks-editor.css';
import './blocks.css';
import {BlocksApp} from './Blocks';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><ReactFlowProvider><BlocksApp /></ReactFlowProvider></React.StrictMode>,
);
