const scrollCart = document.querySelector('[data-scroll-cart]');
const cartNavbar = document.querySelector('.hero-panel > .navbar, .product-header');

if (scrollCart && cartNavbar) {
    const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
    let placeholder = null;
    let positionAnimation = null;
    let floating = false;
    let scrollFrame = null;
    const navbarThreshold = cartNavbar.getBoundingClientRect().height;

    function moveCart(shouldFloat) {
        if (shouldFloat === floating) return;

        const start = scrollCart.getBoundingClientRect();
        if (positionAnimation) {
            positionAnimation.cancel();
            positionAnimation = null;
        }

        if (shouldFloat) {
            placeholder = document.createElement('span');
            placeholder.className = 'cart-slot';
            placeholder.setAttribute('aria-hidden', 'true');
            scrollCart.before(placeholder);
            document.body.append(scrollCart);
            scrollCart.classList.add('is-floating');
        } else {
            scrollCart.classList.remove('is-floating');
            placeholder.replaceWith(scrollCart);
            placeholder = null;
        }

        floating = shouldFloat;

        if (motionPreference.matches) return;

        const end = scrollCart.getBoundingClientRect();
        const deltaX = start.left - end.left;
        const deltaY = start.top - end.top;
        if (!deltaX && !deltaY) return;

        positionAnimation = scrollCart.animate(
            [
                { transform: `translate(${deltaX}px, ${deltaY}px)` },
                { transform: 'translate(0, 0)' },
            ],
            {
                duration: 420,
                easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
            },
        );
        positionAnimation.onfinish = () => {
            positionAnimation = null;
        };
    }

    function handleScroll() {
        if (scrollFrame !== null) return;

        scrollFrame = window.requestAnimationFrame(() => {
            const currentScrollY = window.scrollY;
            moveCart(currentScrollY > navbarThreshold);
            scrollFrame = null;
        });
    }

    moveCart(window.scrollY > navbarThreshold);
    window.addEventListener('scroll', handleScroll, { passive: true });
}
