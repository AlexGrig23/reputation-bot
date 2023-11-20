() => {
    const images = document.querySelectorAll('img');
    for (const img of images) {
        if (!img.complete) {
            return false;
        }
    }
    return true;
}