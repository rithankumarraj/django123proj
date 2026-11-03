const quantityInput = document.getElementById('quantity');
const decreaseButton = document.querySelector('[data-quantity-decrease]');
const increaseButton = document.querySelector('[data-quantity-increase]');
const quantityTotal = document.querySelector('[data-quantity-total]');
const buyButton = document.querySelector('.btn-buy');
const cartForm = document.querySelector('.cart-add-form');
const cartQuantityInput = document.querySelector('[data-cart-quantity]');

if (quantityInput && quantityTotal && buyButton) {
    const unitPrice = Number(quantityTotal.dataset.unitPrice);
    const checkoutUrl = new URL(buyButton.href, window.location.href);
    const currencyFormatter = new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        minimumFractionDigits: 2,
    });

    const updateQuantityDetails = () => {
        const quantity = Number(quantityInput.value);
        const isValidQuantity = Number.isSafeInteger(quantity) && quantity >= 1;

        if (!isValidQuantity) {
            quantityTotal.textContent = '—';
            buyButton.setAttribute('aria-disabled', 'true');
            if (cartForm) {
                cartForm.querySelector('button[type="submit"]').disabled = true;
            }
            return;
        }

        quantityTotal.textContent = currencyFormatter.format(unitPrice * quantity);
        if (cartQuantityInput) {
            cartQuantityInput.value = String(quantity);
        }
        checkoutUrl.searchParams.set('qty', String(quantity));
        buyButton.href = checkoutUrl.toString();
        buyButton.removeAttribute('aria-disabled');
        if (cartForm) {
            cartForm.querySelector('button[type="submit"]').disabled = false;
        }
    };

    quantityInput.addEventListener('input', updateQuantityDetails);
    quantityInput.addEventListener('change', () => {
        if (!Number.isSafeInteger(Number(quantityInput.value)) || Number(quantityInput.value) < 1) {
            quantityInput.value = '1';
        }
        updateQuantityDetails();
    });

    if (decreaseButton) {
        decreaseButton.addEventListener('click', () => {
            const current = Number(quantityInput.value);
            quantityInput.value = String(Math.max(1, (Number.isSafeInteger(current) ? current : 1) - 1));
            updateQuantityDetails();
        });
    }

    if (increaseButton) {
        increaseButton.addEventListener('click', () => {
            const current = Number(quantityInput.value);
            if (Number.isSafeInteger(current) && current >= 1 && current < Number.MAX_SAFE_INTEGER) {
                quantityInput.value = String(current + 1);
            } else if (!Number.isSafeInteger(current) || current < 1) {
                quantityInput.value = '1';
            }
            updateQuantityDetails();
        });
    }

    buyButton.addEventListener('click', (event) => {
        if (buyButton.getAttribute('aria-disabled') === 'true') {
            event.preventDefault();
        }
    });

    if (cartForm) {
        cartForm.addEventListener('submit', (event) => {
            if (!Number.isSafeInteger(Number(quantityInput.value)) || Number(quantityInput.value) < 1) {
                event.preventDefault();
            }
        });
    }

    updateQuantityDetails();
}

const pincodeInput = document.getElementById('pincodeCheckInput');
const pincodeBtn = document.getElementById('pincodeCheckBtn');
const pincodeFeedback = document.getElementById('pincodeCheckFeedback');

if (pincodeInput && pincodeBtn && pincodeFeedback) {
    pincodeInput.addEventListener('input', function () {
        this.value = this.value.replace(/\D/g, '').slice(0, 6);
        if (this.value.length < 6) {
            pincodeFeedback.style.display = 'none';
        }
    });

    const doCheck = () => {
        const pin = pincodeInput.value.replace(/\D/g, '').slice(0, 6);
        pincodeInput.value = pin;
        const productId = pincodeInput.dataset.productId;
        if (!pin || pin.length < 6) {
            pincodeFeedback.className = 'small mt-2 text-warning';
            pincodeFeedback.textContent = 'Please enter a valid 6-digit PIN code.';
            pincodeFeedback.style.display = 'block';
            return;
        }
        pincodeBtn.disabled = true;
        pincodeBtn.textContent = '...';
        fetch(`/api/check-pincode/${productId}/?pincode=${encodeURIComponent(pin)}`)
            .then((res) => res.json())
            .then((data) => {
                pincodeFeedback.style.display = 'block';
                if (data.available) {
                    pincodeFeedback.className = 'small mt-2 text-success fw-medium';
                    pincodeFeedback.innerHTML = `✓ ${data.message}`;
                } else {
                    pincodeFeedback.className = 'small mt-2 text-danger fw-medium';
                    pincodeFeedback.innerHTML = `✕ ${data.message}`;
                }
            })
            .catch(() => {
                pincodeFeedback.className = 'small mt-2 text-warning';
                pincodeFeedback.textContent = 'Could not verify PIN code right now. Please try again.';
                pincodeFeedback.style.display = 'block';
            })
            .finally(() => {
                pincodeBtn.disabled = false;
                pincodeBtn.textContent = 'Check';
            });
    };

    pincodeBtn.addEventListener('click', doCheck);
    pincodeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            doCheck();
        }
    });
}
