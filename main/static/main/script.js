const productData = JSON.parse(document.getElementById('products-data').textContent || '[]');
const switcher = document.querySelector('[data-product-switcher]');

if (switcher && productData.length) {
    const display = switcher.querySelector('[data-product-display]');
    const image = switcher.querySelector('[data-product-image]');
    const imageLink = switcher.querySelector('[data-product-image-link]');
    const categoryBadge = switcher.querySelector('[data-product-category-badge]');
    const count = switcher.querySelector('[data-product-count]');
    const name = switcher.querySelector('[data-product-name]');
    const description = switcher.querySelector('[data-product-description]');
    const descriptionToggle = switcher.querySelector('[data-product-description-toggle]');
    const volume = switcher.querySelector('[data-product-volume]');
    const price = switcher.querySelector('[data-product-price]');
    const tiles = [...switcher.querySelectorAll('[data-product-index]')];
    const cartForm = switcher.querySelector('[data-product-add-to-cart]');
    const wishlistForm = switcher.querySelector('[data-product-wishlist]');
    const wishlistButton = wishlistForm?.querySelector('[data-wishlist-button]');
    const cartFeedback = switcher.querySelector('[data-cart-feedback]');
    const cartLink = document.querySelector('[data-scroll-cart]');
    let currentProduct = 0;

    function renderProduct(index, animate = false) {
        const product = productData[index];
        if (!product) return;

        const update = () => {
            const isCombo = Boolean(product.is_combo);
            image.src = product.image;
            image.alt = product.name;
            if (imageLink) {
                imageLink.href = tiles[index].dataset.productUrl;
                imageLink.setAttribute('aria-label', `View ${product.name} details`);
                imageLink.classList.toggle('is-combo', isCombo);
            }
            if (categoryBadge) {
                categoryBadge.textContent = isCombo ? 'COMBO OFFER' : (product.category_display || '');
                categoryBadge.classList.toggle('category-badge--combo', isCombo);
            }
            const nonComboTotal = productData.filter(p => !p.is_combo).length;
            count.textContent = isCombo ? 'COMBO DEAL' : `${index + 1} / ${nonComboTotal}`;
            name.textContent = product.name;
            if (description) {
                description.textContent = product.description;
            }
            if (descriptionToggle) {
                descriptionToggle.setAttribute('aria-label', `Show ${product.name} description`);
            }
            volume.textContent = product.volume;
            if (isCombo && product.original_price) {
                price.innerHTML = `<span style="color: #2fcf7a; font-weight: 800;">₹${product.price}</span> <del style="opacity: 0.55; font-size: 0.82em; margin-left: 6px; font-weight: 400;">₹${product.original_price}</del> <span class="badge" style="background: rgba(47, 207, 122, 0.2); color: #2fcf7a; font-size: 0.72em; margin-left: 8px; padding: 3px 8px; border-radius: 999px;">${product.discount_display || 'SPECIAL OFFER'}</span>`;
            } else {
                price.textContent = `₹${Number(product.price).toFixed(0)}`;
            }
            const shopLink = switcher.querySelector('[data-product-shop]');
            if (shopLink) {
                shopLink.style.display = isCombo ? 'none' : '';
            }
            if (cartForm) {
                cartForm.action = tiles[index].dataset.addToCartUrl;
                const addBtn = cartForm.querySelector('button');
                if (addBtn) {
                    addBtn.textContent = isCombo ? 'Add Combo to Cart' : 'Add to cart';
                }
            }
            if (wishlistForm) {
                wishlistForm.style.display = isCombo ? 'none' : '';
                if (!isCombo) {
                    wishlistForm.action = tiles[index].dataset.wishlistUrl;
                    const isWishlisted = tiles[index].dataset.isWishlisted === 'true';
                    wishlistButton.textContent = isWishlisted ? '♥ Saved' : '♡ Wishlist';
                    wishlistButton.setAttribute('aria-pressed', String(isWishlisted));
                }
            }

            tiles.forEach((tile, tileIndex) => {
                const selected = tileIndex === index;
                tile.classList.toggle('is-selected', selected);
                tile.setAttribute('aria-selected', String(selected));
            });

            if (display) display.classList.remove('is-changing');
        };

        if (!animate) {
            update();
            return;
        }

        if (display) display.classList.add('is-changing');
        window.setTimeout(update, 180);
    }

    if (descriptionToggle && description) {
        descriptionToggle.addEventListener('click', () => {
            const isExpanded = descriptionToggle.getAttribute('aria-expanded') === 'true';
            descriptionToggle.setAttribute('aria-expanded', String(!isExpanded));
            description.hidden = isExpanded;
        });
    }

    tiles.forEach((tile) => {
        tile.addEventListener('click', (event) => {
            const nextProduct = Number(tile.dataset.productIndex);
            if (event.detail === 2) {
                addProductToCart(tile);
                return;
            }
            if (nextProduct === currentProduct) return;
            currentProduct = nextProduct;
            renderProduct(currentProduct, true);
        });
    });

    const categoryFilters = document.querySelector('[data-category-filters]');
    const totalCountEl = document.querySelector('.product-total');
    let activeCategory = 'all';

    if (categoryFilters) {
        const pills = categoryFilters.querySelectorAll('[data-filter-category]');
        pills.forEach((pill) => {
            pill.addEventListener('click', () => {
                const targetCategory = pill.dataset.filterCategory;
                if (targetCategory === activeCategory) return;
                activeCategory = targetCategory;

                pills.forEach((p) => {
                    const isActive = p === pill;
                    p.classList.toggle('is-active', isActive);
                    p.setAttribute('aria-selected', String(isActive));
                });

                let visibleCount = 0;
                let firstVisibleIndex = -1;
                let currentIsVisible = false;

                tiles.forEach((tile) => {
                    const idx = Number(tile.dataset.productIndex);
                    const prodCategory = tile.dataset.productCategory;
                    const isCombo = tile.dataset.isCombo === 'true';

                    let matches = false;
                    if (activeCategory === 'all') {
                        matches = !isCombo;
                    } else if (activeCategory === 'combo') {
                        matches = isCombo;
                    } else {
                        matches = (prodCategory === activeCategory) && !isCombo;
                    }

                    if (matches) {
                        tile.classList.remove('is-hidden');
                        tile.removeAttribute('hidden');
                        tile.style.display = '';
                        visibleCount++;
                        if (firstVisibleIndex === -1) {
                            firstVisibleIndex = idx;
                        }
                        if (idx === currentProduct) {
                            currentIsVisible = true;
                        }
                    } else {
                        tile.classList.add('is-hidden');
                        tile.setAttribute('hidden', '');
                        tile.style.display = 'none';
                    }
                });

                if (totalCountEl) {
                    if (activeCategory === 'combo') {
                        totalCountEl.textContent = `${visibleCount} combo offer${visibleCount === 1 ? '' : 's'}`;
                    } else {
                        totalCountEl.textContent = `${visibleCount} product${visibleCount === 1 ? '' : 's'}`;
                    }
                }

                if (!currentIsVisible && firstVisibleIndex !== -1) {
                    currentProduct = firstVisibleIndex;
                    renderProduct(currentProduct, true);
                }
            });
        });
    }

    async function addProductToCart(tile) {
        const productIndex = Number(tile.dataset.productIndex);
        const product = productData[productIndex];
        const csrfToken = cartForm?.querySelector('[name="csrfmiddlewaretoken"]')?.value;
        if (!cartFeedback) {
            console.error('Cart feedback element is missing.');
            return;
        }
        if (!product || !csrfToken) {
            cartFeedback.textContent = 'Could not add this product to your cart. Please refresh and try again.';
            return;
        }

        currentProduct = productIndex;
        renderProduct(currentProduct);
        cartFeedback.textContent = `Adding ${product.name} to your cart…`;

        try {
            const response = await fetch(tile.dataset.addToCartUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: new URLSearchParams({ quantity: '1' }),
            });
            if (!response.ok) {
                throw new Error('Could not add this product to your cart. Please try again.');
            }

            const result = await response.json();
            if (result.redirect_url) {
                window.location.href = result.redirect_url;
                return;
            }
            const cartCount = cartLink?.querySelector('.cart-count');
            if (cartCount && cartLink) {
                cartCount.textContent = String(result.cart_count);
                cartLink.setAttribute(
                    'aria-label',
                    `Shopping cart, ${result.cart_count} item${result.cart_count === 1 ? '' : 's'}`,
                );
            }

            cartFeedback.textContent = `${product.name} added to your cart.`;
            animateProductToCart(tile);
        } catch (error) {
            cartFeedback.textContent = error instanceof Error
                ? error.message
                : 'Could not add this product to your cart. Please try again.';
        }
    }

    function animateProductToCart(tile) {
        if (!cartLink) return;

        const source = tile.querySelector('img');
        const target = cartLink.querySelector('.cart-icon');
        if (!source || !target || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return;
        }

        const start = source.getBoundingClientRect();
        const end = target.getBoundingClientRect();
        const startX = start.left + start.width / 2;
        const startY = start.top + start.height / 2;
        const endX = end.left + end.width / 2;
        const endY = end.top + end.height / 2;
        const distance = Math.hypot(endX - startX, endY - startY);
        const curve = Math.min(120, distance * 0.18);
        const controlX = (startX + endX) / 2 - curve;
        const controlY = (startY + endY) / 2 - curve;
        const flightImage = source.cloneNode();

        flightImage.className = 'product-cart-flight';
        Object.assign(flightImage.style, {
            position: 'fixed',
            left: `${start.left}px`,
            top: `${start.top}px`,
            width: `${start.width}px`,
            height: `${start.height}px`,
            objectFit: 'contain',
            pointerEvents: 'none',
            zIndex: '1200',
            transformOrigin: 'center',
        });
        document.body.append(flightImage);

        const keyframes = Array.from({ length: 25 }, (_, frame) => {
            const progress = frame / 24;
            const inverse = 1 - progress;
            const x = inverse ** 2 * startX + 2 * inverse * progress * controlX + progress ** 2 * endX;
            const y = inverse ** 2 * startY + 2 * inverse * progress * controlY + progress ** 2 * endY;
            const scale = 1 - progress * 0.88;
            return {
                transform: `translate(${x - startX}px, ${y - startY}px) scale(${scale}) rotate(${progress * 12}deg)`,
                opacity: 1 - progress * 0.2,
            };
        });
        const flight = flightImage.animate(keyframes, {
            duration: 720,
            easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
        });
        flight.onfinish = () => flightImage.remove();

        target.animate(
            [
                { transform: 'scale(1)' },
                { transform: 'scale(1.35)' },
                { transform: 'scale(1)' },
            ],
            { duration: 420, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' },
        );
    }

    const productLink = switcher.querySelector('[data-product-shop]');
    if (productLink) {
        productLink.addEventListener('click', (event) => {
            event.preventDefault();
            const url = tiles[currentProduct]?.dataset?.productUrl;
            if (url) window.location.href = url;
        });
    }

    renderProduct(currentProduct);
}
