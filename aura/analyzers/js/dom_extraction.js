(opts) => {
    // Canonical AURA DOM evidence extraction. Shared by the Playwright collector (aura/analyzers/dom_analyzer.py)
    // and the Chrome extension (extension/content/dom_extraction.js is generated from this file by
    // `python -m aura.tools.sync_extension_assets`; do not edit the copy).
    // opts.collectFieldValues=false (extension, live user session): never read what the user typed into
    // form fields; only button-like inputs keep their value, which is their visible label.
    const collectFieldValues = !(opts && opts.collectFieldValues === false);
    const BUTTON_INPUT_TYPES = ['button', 'submit', 'reset'];
    const fieldValue = (n) => {
        if (n.value === undefined || n.value === null) return '';
        if (collectFieldValues) return n.value;
        const t = (n.getAttribute('type') || '').toLowerCase();
        return (n.tagName === 'INPUT' && BUTTON_INPUT_TYPES.includes(t)) ? n.value : '';
    };
    const elements = [];
    const selectors = 'button, a, input, select, textarea, form, label, h1, h2, h3, h4, h5, h6, img, nav, header, footer, main, section, article, table, div.card, [id], [role="button"], [role="link"], [role="navigation"], [role="alert"], [role="status"], [aria-live]';
    // Non-rendered elements are not page UI (e.g. <script type="application/json" id="...">) and
    // must never enter DOM evidence or become interaction targets.
    const NON_RENDERED = ['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT', 'META', 'LINK', 'TITLE', 'HEAD'];
    // AURA's own temporary overlay (the extension's highlight) is never page evidence.
    const nodes = Array.from(document.querySelectorAll(selectors)).filter(n => !NON_RENDERED.includes(n.tagName) && !n.closest('[data-aura-overlay]'));

    const docScrollWidth = Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0);
    const docClientWidth = Math.max(document.documentElement.clientWidth, document.body ? document.body.clientWidth : 0);
    const hasHorizontalOverflow = docScrollWidth > (docClientWidth + 5);

    // Unique, re-resolvable selector: nearest ancestor id + :nth-of-type path
    const cssPath = (n) => {
        const parts = [];
        for (let p = n; p && p.nodeType === 1 && p !== document.documentElement; p = p.parentElement) {
            if (p.id) { parts.unshift('#' + CSS.escape(p.id)); return parts.join(' > '); }
            let seg = p.tagName.toLowerCase();
            const parent = p.parentElement;
            if (parent) {
                const same = Array.from(parent.children).filter((c) => c.tagName === p.tagName);
                if (same.length > 1) seg += ':nth-of-type(' + (same.indexOf(p) + 1) + ')';
            }
            parts.unshift(seg);
        }
        return parts.join(' > ');
    };
    const idChain = (n) => { const ids = []; for (let p = n; p && p.nodeType === 1; p = p.parentElement) { if (p.id) ids.push(p.id); } return ids; };

    for (const node of nodes) {
        const rect = node.getBoundingClientRect();
        const computedStyle = window.getComputedStyle(node);
        const isVisible = rect.width > 0 && rect.height > 0 && 
                          computedStyle.visibility !== 'hidden' && 
                          computedStyle.display !== 'none' && 
                          computedStyle.opacity !== '0';

        const tag = node.tagName.toLowerCase();
        const ownText = (node.tagName === 'TEXTAREA' && !collectFieldValues) ? '' : node.innerText;
        const text = (ownText || fieldValue(node) || node.getAttribute('alt') || '').trim();
        const ariaLabel = node.getAttribute('aria-label');
        const accessibleName = ariaLabel || text || node.getAttribute('title') || node.getAttribute('placeholder') || null;

        const clipsX = ['hidden', 'clip'].includes(computedStyle.overflowX);
        const clipsY = ['hidden', 'clip'].includes(computedStyle.overflowY);
        const isRoot = tag === 'body' || tag === 'html';
        elements.push({
            tag: tag,
            selector: cssPath(node),
            id_chain: idChain(node),
            overflows_viewport: isVisible && rect.right > docClientWidth + 1,
            contains_overflow: isVisible && !isRoot && node.scrollWidth > node.clientWidth + 1 && !clipsX,
            clipped: isVisible && !isRoot && ((clipsX && node.scrollWidth > node.clientWidth + 1) || (clipsY && node.scrollHeight > node.clientHeight + 1)),
            role: node.getAttribute('role') || null,
            accessible_name: accessibleName ? accessibleName.substring(0, 100) : null,
            text: text.substring(0, 100),
            aria_label: ariaLabel || null,
            id: node.id || null,
            class_name: node.className && typeof node.className === 'string' ? node.className : null,
            visible: isVisible,
            enabled: !node.disabled,
            bounding_box: isVisible ? {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            } : null,
            computed_style: isVisible ? {
                display: computedStyle.display,
                position: computedStyle.position,
                overflow: computedStyle.overflow,
                color: computedStyle.color,
                background_color: computedStyle.backgroundColor,
                font_size: computedStyle.fontSize,
                font_weight: computedStyle.fontWeight
            } : null,
            href: node.getAttribute('href') || null,
            src: node.getAttribute('src') || null,
            alt: node.getAttribute('alt') || null,
            type: node.getAttribute('type') || null,
            placeholder: node.getAttribute('placeholder') || null
        });
    }
    return {
        doc_scroll_width: docScrollWidth,
        doc_client_width: docClientWidth,
        has_horizontal_overflow: hasHorizontalOverflow,
        elements: elements
    };
}
