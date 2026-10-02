document.addEventListener('DOMContentLoaded', () => {
    console.log('AURA Demo Website loaded successfully.');

    const ctaBtn = document.getElementById('main-cta-btn');
    if (ctaBtn) {
        ctaBtn.addEventListener('click', () => {
            alert('CTA Button Clicked!');
        });
    }

    const contactForm = document.getElementById('contact-form');
    if (contactForm) {
        contactForm.addEventListener('submit', (e) => {
            e.preventDefault();
            alert('Form submitted successfully!');
        });
    }
});

