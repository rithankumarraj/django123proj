document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-quantity-step]');
    if (!button) return;

    const control = button.closest('.cart-quantity-control');
    const input = control?.querySelector('.cart-quantity');
    if (!input) return;

    const current = Number(input.value);
    const step = Number(button.dataset.quantityStep);
    const minimum = Number(input.min) || 1;
    const maximum = Number(input.max) || 1_000_000;
    const quantity = Number.isSafeInteger(current) ? current : minimum;

    input.value = String(Math.min(maximum, Math.max(minimum, quantity + step)));
    input.dispatchEvent(new Event('input', { bubbles: true }));
});

const cartForm = document.querySelector('[data-cart-update-form]');
const saveStatus = document.querySelector('[data-cart-save-status]');

if (cartForm && saveStatus) {
    let saveTimer = null;
    let saving = false;
    let saveQueued = false;

    function formatMoney(value) {
        return `₹${Number(value).toFixed(2)}`;
    }

    function updateTotals() {
        let totalQuantity = 0;
        let cartTotal = 0;

        cartForm.querySelectorAll('.cart-item').forEach((item) => {
            const input = item.querySelector('.cart-quantity');
            const lineTotal = item.querySelector('[data-line-total]');
            const quantity = Number(input?.value);
            const unitPrice = Number(input?.dataset.unitPrice);
            if (!Number.isSafeInteger(quantity) || quantity < 1 || !Number.isFinite(unitPrice)) {
                return;
            }

            const lineAmount = quantity * unitPrice;
            totalQuantity += quantity;
            cartTotal += lineAmount;
            if (lineTotal) lineTotal.textContent = formatMoney(lineAmount);
        });

        const count = document.querySelector('[data-cart-count]');
        const total = document.querySelector('[data-cart-total]');
        if (count) count.textContent = `${totalQuantity} item${totalQuantity === 1 ? '' : 's'}`;
        if (total) total.textContent = formatMoney(cartTotal);

        if (typeof window.updateCartCalculations === 'function') {
            window.updateCartCalculations();
        } else {
            const checkoutTotal = document.querySelector('[data-cart-checkout-total]');
            if (checkoutTotal) checkoutTotal.textContent = `Continue to payment · ${formatMoney(cartTotal)}`;
        }
    }

    async function saveCart() {
        if (saving) {
            saveQueued = true;
            return;
        }

        saving = true;
        saveQueued = false;
        saveStatus.textContent = 'Saving cart…';
        try {
            const response = await fetch(cartForm.getAttribute('action'), {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': cartForm.querySelector('[name="csrfmiddlewaretoken"]').value,
                },
                body: new FormData(cartForm),
            });
            if (!response.ok) {
                throw new Error('Your cart could not be saved. Please try again.');
            }

            const result = await response.json();
            const serverItems = new Map(result.items.map((item) => [String(item.product_id), item]));
            cartForm.querySelectorAll('.cart-item').forEach((item) => {
                const input = item.querySelector('.cart-quantity');
                const productId = input.name.replace('quantity_', '');
                const serverItem = serverItems.get(productId);
                const lineTotal = item.querySelector('[data-line-total]');
                if (serverItem && lineTotal) {
                    lineTotal.textContent = formatMoney(serverItem.line_total);
                }
            });

            const count = document.querySelector('[data-cart-count]');
            const total = document.querySelector('[data-cart-total]');
            if (count) {
                count.textContent = `${result.cart_count} item${result.cart_count === 1 ? '' : 's'}`;
            }
            if (total) total.textContent = formatMoney(result.cart_total);

            if (typeof result.combo_active !== 'undefined' && typeof window.setCartComboData === 'function') {
                window.setCartComboData(result.combo_active, result.combo_name, parseFloat(result.combo_discount) || 0, result.combo_eligible_ids || []);
            } else if (typeof window.updateCartCalculations === 'function') {
                window.updateCartCalculations();
            } else {
                const checkoutTotal = document.querySelector('[data-cart-checkout-total]');
                if (checkoutTotal) {
                    checkoutTotal.textContent = `Continue to payment · ${formatMoney(result.cart_total)}`;
                }
            }
            saveStatus.textContent = 'Cart updated.';
        } catch (error) {
            saveStatus.textContent = error instanceof Error
                ? error.message
                : 'Your cart could not be saved. Please try again.';
        } finally {
            saving = false;
            if (saveQueued) {
                saveCart();
            }
        }
    }

    cartForm.addEventListener('input', (event) => {
        if (!event.target.matches('.cart-quantity')) return;
        updateTotals();
        saveStatus.textContent = 'Saving cart…';
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(saveCart, 250);
    });
}
