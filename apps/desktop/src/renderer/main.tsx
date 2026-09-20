import {installDebugLog} from './debug-log';
import React from 'react';
import {createRoot} from 'react-dom/client';
import '@fontsource-variable/inter';
import 'dockview-react/dist/styles/dockview.css';
import App from './App';
import './style.css';
installDebugLog();

const hideScrollbar = new WeakMap<Element, number>()
document.addEventListener('scroll', event => {
  const el = event.target instanceof Element ? event.target : document.documentElement
  el.classList.add('sb-show')
  const prior = hideScrollbar.get(el)
  if (prior) window.clearTimeout(prior)
  hideScrollbar.set(el, window.setTimeout(() => {
    el.classList.remove('sb-show')
    hideScrollbar.delete(el)
  }, 800))
}, {capture: true, passive: true})

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
