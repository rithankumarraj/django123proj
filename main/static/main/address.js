/**
 * Address control script for checkout and cart pages.
 * Handles '+ Add address', multi-address card selection (up to 5 saved addresses),
 * and 'Use saved address' toggling, clearing, and focusing.
 */
(function () {
    function initAddressControl() {
        const addAddressBtn = document.getElementById('btn-add-address');
        const useSavedBtn = document.getElementById('btn-use-saved-address');
        const savedDataEl = document.getElementById('saved-address-data');
        const savedPreview = document.getElementById('saved-address-preview');
        const addressCards = document.querySelectorAll('.address-select-card');
        const addressBadge = document.getElementById('address-mode-badge');

        const phoneInput = document.getElementById('delivery-phone') || document.getElementById('phone');
        const addressInput = document.getElementById('delivery-address') || document.getElementById('address');
        const cityInput = document.getElementById('delivery-city') || document.getElementById('city');
        const stateInput = document.getElementById('delivery-state') || document.getElementById('state');
        const zipInput = document.getElementById('delivery-postal-code') || document.getElementById('zip');

        if (!addAddressBtn) return;

        function applyAddressData(data) {
            if (phoneInput && data.phone) {
                let digits = String(data.phone).replace(/\D/g, '');
                if (digits.length === 12 && digits.startsWith('91')) {
                    digits = digits.slice(2);
                } else if (digits.length === 11 && digits.startsWith('0')) {
                    digits = digits.slice(1);
                } else if (digits.length > 10) {
                    digits = digits.slice(-10);
                }
                phoneInput.value = digits;
                phoneInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
            if (addressInput && data.address) addressInput.value = data.address;
            if (cityInput && data.city) cityInput.value = data.city;
            if (stateInput && data.state) {
                let found = false;
                if (stateInput.options) {
                    for (let i = 0; i < stateInput.options.length; i++) {
                        if (stateInput.options[i].value.toLowerCase() === String(data.state).trim().toLowerCase()) {
                            stateInput.selectedIndex = i;
                            found = true;
                            break;
                        }
                    }
                }
                if (!found) {
                    stateInput.value = data.state;
                }
                stateInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
            if (zipInput && data.postalCode) zipInput.value = data.postalCode;
        }

        // Handle clicking any saved address card
        addressCards.forEach(function (card) {
            card.addEventListener('click', function () {
                addressCards.forEach(function (c) {
                    c.classList.remove('active');
                    c.classList.remove('saved-address-dimmed');
                });
                if (savedPreview) {
                    savedPreview.classList.remove('saved-address-dimmed');
                }

                card.classList.add('active');

                applyAddressData({
                    phone: card.dataset.phone,
                    address: card.dataset.address,
                    city: card.dataset.city,
                    state: card.dataset.state,
                    postalCode: card.dataset.postalCode
                });

                if (useSavedBtn) useSavedBtn.style.display = 'none';
                if (addressBadge) addressBadge.style.display = 'none';
                addAddressBtn.textContent = '+ Add address';

                const targetFocus = addressInput || phoneInput;
                if (targetFocus) {
                    targetFocus.classList.remove('address-input-pulse');
                    void targetFocus.offsetWidth;
                    targetFocus.classList.add('address-input-pulse');
                }
            });
        });

        addAddressBtn.addEventListener('click', function () {
            // Clear address inputs so the user can easily type a new address
            if (addressInput) addressInput.value = '';
            if (cityInput) cityInput.value = '';
            if (stateInput) {
                stateInput.value = '';
                stateInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
            if (zipInput) zipInput.value = '';

            // Deactivate and dim all saved address cards
            addressCards.forEach(function (c) {
                c.classList.remove('active');
                c.classList.add('saved-address-dimmed');
            });

            if (savedPreview) {
                savedPreview.classList.add('saved-address-dimmed');
            }

            // If there's a saved address, show the 'Use saved address' option
            if (useSavedBtn && (savedDataEl || addressCards.length > 0)) {
                useSavedBtn.style.display = 'inline-flex';
            }
            if (addressBadge) {
                addressBadge.style.display = 'inline-block';
            }
            addAddressBtn.textContent = 'Clear address fields';

            // Focus and pulse on the address input
            const targetFocus = addressInput || phoneInput;
            if (targetFocus) {
                targetFocus.focus();
                targetFocus.classList.remove('address-input-pulse');
                void targetFocus.offsetWidth;
                targetFocus.classList.add('address-input-pulse');
            }
        });

        if (useSavedBtn) {
            useSavedBtn.addEventListener('click', function () {
                // Find active or default card
                const defaultCard = document.querySelector('.address-select-card[data-is-default="1"]') || addressCards[0];
                if (defaultCard) {
                    addressCards.forEach(function (c) {
                        c.classList.remove('active');
                        c.classList.remove('saved-address-dimmed');
                    });
                    defaultCard.classList.add('active');
                    applyAddressData({
                        phone: defaultCard.dataset.phone,
                        address: defaultCard.dataset.address,
                        city: defaultCard.dataset.city,
                        state: defaultCard.dataset.state,
                        postalCode: defaultCard.dataset.postalCode
                    });
                } else if (savedDataEl) {
                    applyAddressData({
                        phone: savedDataEl.dataset.phone,
                        address: savedDataEl.dataset.address,
                        city: savedDataEl.dataset.city,
                        state: savedDataEl.dataset.state,
                        postalCode: savedDataEl.dataset.postalCode
                    });
                }

                useSavedBtn.style.display = 'none';
                if (savedPreview) {
                    savedPreview.classList.remove('saved-address-dimmed');
                }
                if (addressBadge) {
                    addressBadge.style.display = 'none';
                }
                addAddressBtn.textContent = '+ Add address';

                const targetFocus = addressInput || phoneInput;
                if (targetFocus) {
                    targetFocus.focus();
                    targetFocus.classList.remove('address-input-pulse');
                    void targetFocus.offsetWidth;
                    targetFocus.classList.add('address-input-pulse');
                }
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAddressControl);
    } else {
        initAddressControl();
    }
})();
