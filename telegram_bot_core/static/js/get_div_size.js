() => {
    const myDiv = document.getElementById('div-size');

    // Отримання розмірів елемента
    const width = myDiv.offsetWidth;
    const height = myDiv.offsetHeight;

    return {
        width: width,
        height: height
    };
}