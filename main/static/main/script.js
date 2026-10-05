const productData = JSON.parse(document.getElementById('products-data').textContent || '[]');
const switcher = document.querySelector('[data-product-switcher]');

if (switcher && productData.length) {
    const display = switcher.querySelector('[data-product-display]');
    const image = switcher.querySelector('[data-product-image]');
    const count = switcher.querySelector('[data-product-count]');
    const name = switcher.querySelector('[data-product-name]');
    const volume = switcher.querySelector('[data-product-volume]');
    const price = switcher.querySelector('[data-product-price]');
    const tiles = [...switcher.querySelectorAll('[data-product-index]')];
    let currentProduct = 0;

    function renderProduct(index, animate = false) {
        const product = productData[index];
        if (!product) return;

        const update = () => {
            image.src = product.image;
            image.alt = product.name;
            count.textContent = `${index + 1} / ${productData.length}`;
            name.textContent = product.name;
            volume.textContent = product.volume;
            price.textContent = `₹${Number(product.price).toFixed(0)}`;

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

    tiles.forEach((tile) => {
        tile.addEventListener('click', () => {
            const nextProduct = Number(tile.dataset.productIndex);
            if (nextProduct === currentProduct) return;
            currentProduct = nextProduct;
            renderProduct(currentProduct, true);
        });
    });

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
