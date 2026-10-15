"use strict";(self.webpackChunk_N_E=self.webpackChunk_N_E||[]).push([[950],{5003:(e,t,r)=>{r.d(t,{Uw:()=>u,Vx:()=>c,bU:()=>b,li:()=>m,p1:()=>l});var s=r(69515),n=r(3796);function i(e){for(var t=1;t<arguments.length;t++){var r=null!=arguments[t]?arguments[t]:{},s=Object.keys(r);"function"==typeof Object.getOwnPropertySymbols&&(s=s.concat(Object.getOwnPropertySymbols(r).filter(function(e){return Object.getOwnPropertyDescriptor(r,e).enumerable}))),s.forEach(function(t){var s;s=r[t],t in e?Object.defineProperty(e,t,{value:s,enumerable:!0,configurable:!0,writable:!0}):e[t]=s})}return e}function o(e,t){if(null==e)return{};var r,s,n=function(e,t){if(null==e)return{};var r,s,n={},i=Object.keys(e);for(s=0;s<i.length;s++)r=i[s],t.indexOf(r)>=0||(n[r]=e[r]);return n}(e,t);if(Object.getOwnPropertySymbols){var i=Object.getOwnPropertySymbols(e);for(s=0;s<i.length;s++)r=i[s],!(t.indexOf(r)>=0)&&Object.prototype.propertyIsEnumerable.call(e,r)&&(n[r]=e[r])}return n}var a=(0,n.createContext)(void 0),l=function(){var e=(0,n.useContext)(a);if(!e)throw Error("useProgress must be used within a ProgressProvider");return e},c=function(e){var t=e.children,r=e.color,o=void 0===r?"#0A2FFF":r,l=e.height,c=void 0===l?"2px":l,u=e.options,p=e.spinnerPosition,d=void 0===p?"top-right":p,h=e.style,f=e.disableStyle,g=e.nonce,m=e.shallowRouting,b=e.disableSameURL,y=e.startPosition,v=e.delay,P=e.stopDelay,S=(0,n.useRef)(null),w=(0,n.useRef)(!1),O=(0,n.useCallback)(function(){return w.current=!0},[]),k=(0,n.useCallback)(function(){return w.current=!1},[]),x=(0,n.useCallback)(function(){var e=arguments.length>0&&void 0!==arguments[0]?arguments[0]:0,t=arguments.length>1&&void 0!==arguments[1]?arguments[1]:0,r=arguments.length>2&&void 0!==arguments[2]&&arguments[2];r&&O(),S.current=setTimeout(function(){e>0&&s.i3.set(e),s.i3.start()},t)},[O]),E=(0,n.useCallback)(function(){var e=arguments.length>0&&void 0!==arguments[0]?arguments[0]:0,t=arguments.length>1&&void 0!==arguments[1]?arguments[1]:0;setTimeout(function(){S.current&&clearTimeout(S.current),S.current=setTimeout(function(){s.i3.isStarted()&&(s.i3.done(),w.current&&k())},e)},t)},[k]),R=(0,n.useCallback)(function(e){return s.i3.inc(e)},[]),j=(0,n.useCallback)(function(e){return s.i3.dec(e)},[]),U=(0,n.useCallback)(function(e){return s.i3.set(e)},[]),C=(0,n.useCallback)(function(){return s.i3.pause()},[]),D=(0,n.useCallback)(function(){return s.i3.resume()},[]),L=(0,n.useCallback)(function(){return s.i3.settings},[]),N=(0,n.useCallback)(function(e){var t=L(),r="function"==typeof e?e(t):e,n=i({},t,r);s.i3.configure(n)},[L]),A=(0,n.useMemo)(function(){return n.createElement("style",{nonce:g},h||(0,s.AH)({color:o,height:c,spinnerPosition:d}))},[o,c,g,d,h]);return s.i3.configure(u||{}),n.createElement(a.Provider,{value:{start:x,stop:E,inc:R,dec:j,set:U,pause:C,resume:D,setOptions:N,getOptions:L,isAutoStopDisabled:w,disableAutoStop:O,enableAutoStop:k,shallowRouting:void 0!==m&&m,disableSameURL:void 0===b||b,startPosition:void 0===y?0:y,delay:void 0===v?0:v,stopDelay:void 0===P?0:P}},void 0!==f&&f?null:A,t)};function u(e){var t=e.shallowRouting,r=void 0!==t&&t,i=e.disableSameURL,o=void 0===i||i,a=e.startPosition,c=void 0===a?0:a,u=e.delay,p=void 0===u?0:u,d=e.stopDelay,h=void 0===d?0:d,f=e.targetPreprocessor,g=e.disableAnchorClick,m=void 0!==g&&g,b=e.startOnLoad,y=void 0!==b&&b,v=e.forcedStopDelay,P=void 0===v?0:v,S=arguments.length>1&&void 0!==arguments[1]?arguments[1]:[],w=(0,n.useRef)([]),O=(0,n.useRef)(null),k=l(),x=k.start,E=k.stop,R=k.isAutoStopDisabled;(0,n.useEffect)(function(){y&&x(c,p)},[]),(0,n.useEffect)(function(){return O.current&&clearTimeout(O.current),O.current=setTimeout(function(){R.current||E()},h),function(){O.current&&clearTimeout(O.current)}},S),(0,n.useEffect)(function(){if(!m){var e=function(e){if(e.defaultPrevented)return;var t=e.currentTarget;if(!t.hasAttribute("download")){var n=e.target,i=(null==n?void 0:n.getAttribute("data-prevent-progress"))==="true"||(null==t?void 0:t.getAttribute("data-prevent-progress"))==="true";if(!i)for(var a,l=n;l&&"a"!==l.tagName.toLowerCase();){if((null==(a=l.parentElement)?void 0:a.getAttribute("data-prevent-progress"))==="true"){i=!0;break}l=l.parentElement}if(!i&&"_blank"!==(0,s.zu)(t,"target")&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey){var u=(0,s.zu)(t,"href"),d=f?f(new URL(u)):new URL(u),h=new URL(location.href);r&&(0,s.uS)(d,h)&&o||(0,s.W_)(d,h)&&o||x(c,p)}}},t=new MutationObserver(function(){var t=Array.from(document.querySelectorAll("a")).filter(function(e){var t=(0,s.zu)(e,"href"),r="true"===e.getAttribute("data-disable-progress"),n=t&&!t.startsWith("tel:")&&!t.startsWith("mailto:")&&!t.startsWith("blob:")&&!t.startsWith("javascript:");return!r&&n&&"_blank"!==(0,s.zu)(e,"target")});t.forEach(function(t){t.addEventListener("click",e,!0)}),w.current=t});t.observe(document,{childList:!0,subtree:!0});var n=window.history.pushState;return window.history.pushState=new Proxy(window.history.pushState,{apply:function(e,t,r){return R.current||E(h,P),e.apply(t,r)}}),function(){t.disconnect(),w.current.forEach(function(t){t.removeEventListener("click",e,!0)}),w.current=[],window.history.pushState=n}}},[m,f,r,o,p,h,c,x,E,P,R])}function p(){for(var e=arguments.length,t=Array(e),r=0;r<e;r++)t[r]=arguments[r];return t.filter(Boolean).join(" ")}var d=n.forwardRef(function(e,t){var r=e.as,s=e.children,a=e.className,l=e.classSelector,c=o(e,["as","children","className","classSelector"]);return n.createElement(null!=r?r:"div",i({ref:t,className:p(void 0===l?"bar":l,a)},c),s)}),h=n.forwardRef(function(e,t){var r=e.as,s=e.children,a=e.className,l=e.classSelector,c=o(e,["as","children","className","classSelector"]);return n.createElement(null!=r?r:"div",i({ref:t,className:p(void 0===l?"peg":l,a)},c),s)}),f=n.forwardRef(function(e,t){var r=e.as,s=e.children,a=e.className,l=e.classSelector,c=o(e,["as","children","className","classSelector"]);return n.createElement(null!=r?r:"div",i({ref:t,className:p(void 0===l?"spinner":l,a)},c),s)}),g=n.forwardRef(function(e,t){var r=e.as,s=e.children,a=e.className,l=e.classSelector,c=o(e,["as","children","className","classSelector"]);return n.createElement(null!=r?r:"div",i({ref:t,className:p(void 0===l?"spinner-icon":l,a)},c),s)});function m(e){return function(t){return n.createElement(n.Suspense,null,n.createElement(e,i({},t)))}}function b(e){var t=arguments.length>1&&void 0!==arguments[1]?arguments[1]:["memo","shouldCompareComplexProps"];return(0,n.memo)(e,function(e,r){return!1!==r.memo&&(!r.shouldCompareComplexProps||function(e,t){var r=arguments.length>2&&void 0!==arguments[2]?arguments[2]:[],s=Object.keys(e).filter(function(e){return!r.includes(e)}),n=Object.keys(t).filter(function(e){return!r.includes(e)});if(s.length!==n.length)return!1;var i=!0,o=!1,a=void 0;try{for(var l,c=s[Symbol.iterator]();!(i=(l=c.next()).done);i=!0){var u=l.value;if(e[u]!==t[u])return!1}}catch(e){o=!0,a=e}finally{try{i||null==c.return||c.return()}finally{if(o)throw a}}return!0}(e,r,t))})}n.forwardRef(function(e,t){var r,s,a=e.as,l=e.children,c=e.className,u=e.style,m=o(e,["as","children","className","style"]);return n.createElement(null!=a?a:"div",i({ref:t,className:p("bprogress",c),style:(r=i({},u),s=s={display:"none"},Object.getOwnPropertyDescriptors?Object.defineProperties(r,Object.getOwnPropertyDescriptors(s)):(function(e){var t=Object.keys(e);if(Object.getOwnPropertySymbols){var r=Object.getOwnPropertySymbols(e);t.push.apply(t,r)}return t})(Object(s)).forEach(function(e){Object.defineProperty(r,e,Object.getOwnPropertyDescriptor(s,e))}),r)},m),l||n.createElement(n.Fragment,null,n.createElement(d,null,n.createElement(h,null)),n.createElement(f,null,n.createElement(g,null))))}),n.forwardRef(function(e,t){var r=e.as,s=e.className,a=e.classSelector,l=o(e,["as","className","classSelector"]);return n.createElement(null!=r?r:"div",i({ref:t,className:p(void 0===a?"indeterminate":a,s)},l),n.createElement("div",{className:"inc"}),n.createElement("div",{className:"dec"}))})},16556:(e,t,r)=>{var s=r(59580);r.o(s,"useParams")&&r.d(t,{useParams:function(){return s.useParams}}),r.o(s,"usePathname")&&r.d(t,{usePathname:function(){return s.usePathname}}),r.o(s,"useRouter")&&r.d(t,{useRouter:function(){return s.useRouter}}),r.o(s,"useSearchParams")&&r.d(t,{useSearchParams:function(){return s.useSearchParams}})},60950:(e,t,r)=>{r.d(t,{V:()=>f,r:()=>u});var s=r(16556),n=r(3796),i=r(69515),o=r(5003);function a(e){for(var t=1;t<arguments.length;t++){var r=null!=arguments[t]?arguments[t]:{},s=Object.keys(r);"function"==typeof Object.getOwnPropertySymbols&&(s=s.concat(Object.getOwnPropertySymbols(r).filter(function(e){return Object.getOwnPropertyDescriptor(r,e).enumerable}))),s.forEach(function(t){var s;s=r[t],t in e?Object.defineProperty(e,t,{value:s,enumerable:!0,configurable:!0,writable:!0}):e[t]=s})}return e}function l(e,t){return t=null!=t?t:{},Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(t)):(function(e){var t=Object.keys(e);if(Object.getOwnPropertySymbols){var r=Object.getOwnPropertySymbols(e);t.push.apply(t,r)}return t})(Object(t)).forEach(function(r){Object.defineProperty(e,r,Object.getOwnPropertyDescriptor(t,r))}),e}function c(e,t){if(null==e)return{};var r,s,n=function(e,t){if(null==e)return{};var r,s,n={},i=Object.keys(e);for(s=0;s<i.length;s++)r=i[s],t.indexOf(r)>=0||(n[r]=e[r]);return n}(e,t);if(Object.getOwnPropertySymbols){var i=Object.getOwnPropertySymbols(e);for(s=0;s<i.length;s++)r=i[s],!(t.indexOf(r)>=0)&&Object.prototype.propertyIsEnumerable.call(e,r)&&(n[r]=e[r])}return n}function u(e){var t=e||{},r=t.customRouter,u=c(t,["customRouter"]),p=r?r():(0,s.useRouter)(),d=(0,o.p1)(),h=d.start,f=d.stop,g=d.disableSameURL,m=d.startPosition,b=d.delay,y=d.stopDelay,v=(0,n.useRef)(null);function P(e){return function(t,r){var s,n,o=r||{},p=o.showProgress,d=o.startPosition,v=o.disableSameURL,P=o.basePath,S=o.i18nPath,w=o.delay,O=o.stopDelay,k=c(o,["showProgress","startPosition","disableSameURL","basePath","i18nPath","delay","stopDelay"]),x=l(a({},u),{showProgress:p,startPosition:d,disableSameURL:v,basePath:P,i18nPath:S,delay:w,stopDelay:O}),E=void 0!==x.disableSameURL?x.disableSameURL:g,R=void 0!==x.startPosition?x.startPosition:m,j=void 0!==x.delay?x.delay:b,U=void 0!==x.stopDelay?x.stopDelay:y;if(!1===x.showProgress)return e(t,k);var C=new URL(location.href),D=new URL(t,location.href);x.i18nPath&&((n=(s=C).pathname.split("/")).length>1&&n[1]&&(n.splice(1,1),s.pathname=n.join("/")||"/"),C=s),x.basePath&&(D.pathname=x.basePath+("/"!==D.pathname?D.pathname:""));var L=(0,i.W_)(D,C);return L&&E||(h(R,j),setTimeout(function(){L&&f(U)},j||0)),e(t,k)}}function S(e){return function(t){var r=t||{},s=r.showProgress,n=r.startPosition,i=r.disableSameURL,o=r.basePath,p=r.i18nPath,d=r.delay,g=r.stopDelay,v=c(r,["showProgress","startPosition","disableSameURL","basePath","i18nPath","delay","stopDelay"]),P=l(a({},u),{showProgress:s,startPosition:n,disableSameURL:i,basePath:o,i18nPath:p,delay:d,stopDelay:g}),S=void 0!==P.startPosition?P.startPosition:m,w=void 0!==P.delay?P.delay:b,O=void 0!==P.stopDelay?P.stopDelay:y;if(!1===P.showProgress)return e(v);h(S,w);var k=e(v);return setTimeout(function(){f(O)},w||0),k}}function w(e){return function(t,r){return e(t,r)}}return v.current?(v.current.push=P(p.push),v.current.replace=P(p.replace),v.current.prefetch=w(p.prefetch),v.current.back=S(p.back),v.current.refresh=S(p.refresh),v.current.forward=S(p.forward)):v.current=l(a({},p),{push:P(p.push),replace:P(p.replace),prefetch:w(p.prefetch),back:S(p.back),refresh:S(p.refresh),forward:S(p.forward)}),v.current}var p=(0,o.bU)(function(e){var t=(0,s.usePathname)(),r=(0,s.useSearchParams)();return(0,o.Uw)(e,[t,r]),null});p.displayName="AppProgress";var d=function(e){var t=e.children,r=e.ProgressComponent,s=e.color,i=e.height,l=e.options,u=e.spinnerPosition,p=e.style,d=e.disableStyle,h=e.nonce,f=e.stopDelay,g=e.delay,m=e.startPosition,b=e.disableSameURL,y=e.shallowRouting,v=c(e,["children","ProgressComponent","color","height","options","spinnerPosition","style","disableStyle","nonce","stopDelay","delay","startPosition","disableSameURL","shallowRouting"]);return n.createElement(o.Vx,{color:s,height:i,options:l,spinnerPosition:u,style:p,disableStyle:d,nonce:h,stopDelay:f,delay:g,startPosition:m,disableSameURL:b,shallowRouting:y},n.createElement(r,a({stopDelay:f,delay:g,startPosition:m,disableSameURL:b,shallowRouting:y},v)),t)},h=(0,o.li)(p),f=function(e){var t=e.children,r=c(e,["children"]);return n.createElement(d,a({ProgressComponent:h},r),t)}},69515:(e,t,r)=>{function s(e,t,r){return Math.max(t,Math.min(e,r))}function n(e,t){return"rtl"===t?(1-e)*100:(-1+e)*100}function i(e,t,r){if("string"==typeof t)void 0!==r&&(e.style[t]=r);else for(let r in t)if(t.hasOwnProperty(r)){let s=t[r];void 0!==s&&(e.style[r]=s)}}function o(e,t){e.classList.add(t)}function a(e,t){e.classList.remove(t)}function l(e){e&&e.parentNode&&e.parentNode.removeChild(e)}r.d(t,{AH:()=>p,W_:()=>d,i3:()=>u,uS:()=>h,zu:()=>f});var c={minimum:.08,maximum:1,template:`<div class="bar"><div class="peg"></div></div>
             <div class="spinner"><div class="spinner-icon"></div></div>
             <div class="indeterminate"><div class="inc"></div><div class="dec"></div></div>`,easing:"linear",positionUsing:"",speed:200,trickle:!0,trickleSpeed:200,showSpinner:!0,indeterminate:!1,indeterminateSelector:".indeterminate",barSelector:".bar",spinnerSelector:".spinner",parent:"body",direction:"ltr"},u=class{static settings=c;static status=null;static pending=[];static isPaused=!1;static reset(){return this.status=null,this.isPaused=!1,this.pending=[],this.settings=c,this}static configure(e){return Object.assign(this.settings,e),this}static isStarted(){return"number"==typeof this.status}static set(e){if(this.isPaused)return this;let t=this.isStarted();e=s(e,this.settings.minimum,this.settings.maximum),this.status=e===this.settings.maximum?null:e;let r=this.render(!t),n=this.settings.speed,o=this.settings.easing;return r.forEach(e=>e.offsetWidth),this.queue(t=>{r.forEach(t=>{this.settings.indeterminate||i(t.querySelector(this.settings.barSelector),this.barPositionCSS({n:e,speed:n,ease:o}))}),e===this.settings.maximum?(r.forEach(e=>{i(e,{transition:"none",opacity:"1"}),e.offsetWidth}),setTimeout(()=>{r.forEach(e=>{i(e,{transition:`all ${n}ms ${o}`,opacity:"0"})}),setTimeout(()=>{r.forEach(e=>{this.remove(e),null===this.settings.template&&i(e,{transition:"none",opacity:"1"})}),t()},n)},n)):setTimeout(t,n)}),this}static start(){this.status||this.set(0);let e=()=>{this.isPaused||setTimeout(()=>{this.status&&(this.trickle(),e())},this.settings.trickleSpeed)};return this.settings.trickle&&e(),this}static done(e){return e||this.status?this.inc(.3+.5*Math.random()).set(1):this}static inc(e){if(this.isPaused||this.settings.indeterminate)return this;let t=this.status;return t?t>1?this:("number"!=typeof e&&(e=t>=0&&t<.2?.1:t>=.2&&t<.5?.04:t>=.5&&t<.8?.02:.005*(t>=.8&&t<.99)),t=s(t+e,0,.994),this.set(t)):this.start()}static dec(e){if(this.isPaused||this.settings.indeterminate)return this;let t=this.status;return"number"!=typeof t?this:("number"!=typeof e&&(e=t>.8?.1:t>.5?.05:t>.2?.02:.01),t=s(t-e,0,.994),this.set(t))}static trickle(){return this.isPaused||this.settings.indeterminate?this:this.inc()}static promise(e){if(!e||"resolved"===e.state())return this;let t=0,r=0;return this.start(),t++,r++,e.always(()=>{0==--r?(t=0,this.done()):this.set((t-r)/t)}),this}static render(e=!1){let t="string"==typeof this.settings.parent?document.querySelector(this.settings.parent):this.settings.parent,r=t?Array.from(t.querySelectorAll(".bprogress")):[];if(null!==this.settings.template&&0===r.length){o(document.documentElement,"bprogress-busy");let e=document.createElement("div");o(e,"bprogress"),e.innerHTML=this.settings.template,t!==document.body&&o(t,"bprogress-custom-parent"),t.appendChild(e),r.push(e)}return r.forEach(r=>{if(null===this.settings.template&&(r.style.display=""),o(document.documentElement,"bprogress-busy"),t!==document.body&&o(t,"bprogress-custom-parent"),this.settings.indeterminate){let e=r.querySelector(this.settings.barSelector);e&&(e.style.display="none");let t=r.querySelector(this.settings.indeterminateSelector);t&&(t.style.display="")}else{let t=r.querySelector(this.settings.barSelector),s=e?n(0,this.settings.direction):n(this.status||0,this.settings.direction);i(t,this.barPositionCSS({n:this.status||0,speed:this.settings.speed,ease:this.settings.easing,perc:s}));let o=r.querySelector(this.settings.indeterminateSelector);o&&(o.style.display="none")}if(null===this.settings.template){let e=r.querySelector(this.settings.spinnerSelector);e&&(e.style.display=this.settings.showSpinner?"block":"none")}else if(!this.settings.showSpinner){let e=r.querySelector(this.settings.spinnerSelector);e&&l(e)}}),r}static remove(e){e?null===this.settings.template?e.style.display="none":l(e):(a(document.documentElement,"bprogress-busy"),("string"==typeof this.settings.parent?document.querySelectorAll(this.settings.parent):[this.settings.parent]).forEach(e=>{a(e,"bprogress-custom-parent")}),document.querySelectorAll(".bprogress").forEach(e=>{null===this.settings.template?e.style.display="none":l(e)}))}static pause(){return!this.isStarted()||this.settings.indeterminate||(this.isPaused=!0),this}static resume(){if(!this.isStarted()||this.settings.indeterminate)return this;if(this.isPaused=!1,this.settings.trickle){let e=()=>{this.isPaused||setTimeout(()=>{this.status&&(this.trickle(),e())},this.settings.trickleSpeed)};e()}return this}static isRendered(){return document.querySelectorAll(".bprogress").length>0}static getPositioningCSS(){let e=document.body.style,t="WebkitTransform"in e?"Webkit":"MozTransform"in e?"Moz":"msTransform"in e?"ms":"OTransform"in e?"O":"";return`${t}Perspective`in e?"translate3d":`${t}Transform`in e?"translate":"margin"}static queue(e){this.pending.push(e),1===this.pending.length&&this.next()}static next(){let e=this.pending.shift();e&&e(this.next.bind(this))}static initPositionUsing(){""===this.settings.positionUsing&&(this.settings.positionUsing=this.getPositioningCSS())}static barPositionCSS({n:e,speed:t,ease:r,perc:s}){this.initPositionUsing();let i={},o=s??n(e,this.settings.direction);return"translate3d"===this.settings.positionUsing?i={transform:`translate3d(${o}%,0,0)`}:"translate"===this.settings.positionUsing?i={transform:`translate(${o}%,0)`}:"width"===this.settings.positionUsing?i={width:`${"rtl"===this.settings.direction?100-o:o+100}%`,..."rtl"===this.settings.direction?{right:"0",left:"auto"}:{}}:"margin"===this.settings.positionUsing&&(i="rtl"===this.settings.direction?{"margin-left":`${-o}%`}:{"margin-right":`${-o}%`}),i.transition=`all ${t}ms ${r}`,i}},p=({color:e="#29d",height:t="2px",spinnerPosition:r="top-right"})=>`
:root {
  --bprogress-color: ${e};
  --bprogress-height: ${t};
  --bprogress-spinner-size: 18px;
  --bprogress-spinner-animation-duration: 400ms;
  --bprogress-spinner-border-size: 2px;
  --bprogress-box-shadow: 0 0 10px ${e}, 0 0 5px ${e};
  --bprogress-z-index: 99999;
  --bprogress-spinner-top: ${"top-right"===r||"top-left"===r?"15px":"auto"};
  --bprogress-spinner-bottom: ${"bottom-right"===r||"bottom-left"===r?"15px":"auto"};
  --bprogress-spinner-right: ${"top-right"===r||"bottom-right"===r?"15px":"auto"};
  --bprogress-spinner-left: ${"top-left"===r||"bottom-left"===r?"15px":"auto"};
}

.bprogress {
  width: 0;
  height: 0;
  pointer-events: none;
  z-index: var(--bprogress-z-index);
}

.bprogress .bar {
  background: var(--bprogress-color);
  position: fixed;
  z-index: var(--bprogress-z-index);
  top: 0;
  left: 0;
  width: 100%;
  height: var(--bprogress-height);
}

/* Fancy blur effect */
.bprogress .peg {
  display: block;
  position: absolute;
  right: 0;
  width: 100px;
  height: 100%;
  box-shadow: var(--bprogress-box-shadow);
  opacity: 1.0;
  transform: rotate(3deg) translate(0px, -4px);
}

/* Remove these to get rid of the spinner */
.bprogress .spinner {
  display: block;
  position: fixed;
  z-index: var(--bprogress-z-index);
  top: var(--bprogress-spinner-top);
  bottom: var(--bprogress-spinner-bottom);
  right: var(--bprogress-spinner-right);
  left: var(--bprogress-spinner-left);
}

.bprogress .spinner-icon {
  width: var(--bprogress-spinner-size);
  height: var(--bprogress-spinner-size);
  box-sizing: border-box;
  border: solid var(--bprogress-spinner-border-size) transparent;
  border-top-color: var(--bprogress-color);
  border-left-color: var(--bprogress-color);
  border-radius: 50%;
  -webkit-animation: bprogress-spinner var(--bprogress-spinner-animation-duration) linear infinite;
  animation: bprogress-spinner var(--bprogress-spinner-animation-duration) linear infinite;
}

.bprogress-custom-parent {
  overflow: hidden;
  position: relative;
}

.bprogress-custom-parent .bprogress .spinner,
.bprogress-custom-parent .bprogress .bar {
  position: absolute;
}

.bprogress .indeterminate {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: var(--bprogress-height);
  overflow: hidden;
}

.bprogress .indeterminate .inc,
.bprogress .indeterminate .dec {
  position: absolute;
  top: 0;
  height: 100%;
  background-color: var(--bprogress-color);
}

.bprogress .indeterminate .inc {
  animation: bprogress-indeterminate-increase 2s infinite;
}

.bprogress .indeterminate .dec {
  animation: bprogress-indeterminate-decrease 2s 0.5s infinite;
}

@-webkit-keyframes bprogress-spinner {
  0%   { -webkit-transform: rotate(0deg); transform: rotate(0deg); }
  100% { -webkit-transform: rotate(360deg); transform: rotate(360deg); }
}

@keyframes bprogress-spinner {
  0%   { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

@keyframes bprogress-indeterminate-increase {
  from { left: -5%; width: 5%; }
  to { left: 130%; width: 100%; }
}

@keyframes bprogress-indeterminate-decrease {
  from { left: -80%; width: 80%; }
  to { left: 110%; width: 10%; }
}
`;function d(e,t){return e.protocol+"//"+e.host+e.pathname+e.search==t.protocol+"//"+t.host+t.pathname+t.search}function h(e,t){return e.protocol+"//"+e.host+e.pathname==t.protocol+"//"+t.host+t.pathname}function f(e,t){if("string"==typeof t&&"data-disable-progress"===t){let r=t.substring(5).replace(/-([a-z])/g,(e,t)=>t.toUpperCase());return e.dataset[r]}let r=e[t];if(r instanceof SVGAnimatedString){let e=r.baseVal;return"href"===t?function(e,t){let r,s,n;if(!e.startsWith("/")||!t)return e;let{pathname:i,query:o,hash:a}=(r=e.indexOf("#"),(n=(s=e.indexOf("?"))>-1&&(r<0||s<r))||r>-1?{pathname:e.substring(0,n?s:r),query:n?e.substring(s,r>-1?r:void 0):"",hash:r>-1?e.slice(r):""}:{pathname:e,query:"",hash:""});return`${t}${i}${o}${a}`}(e,location.origin):e}return r}}}]);