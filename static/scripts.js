document.addEventListener("DOMContentLoaded", function () {
    fetch("/get_indices")
        .then(response => response.json())
        .then(indices => {
            const filteredIndices = indices.filter(index => !index.startsWith(".")); // Filtrar los índices del sistema
            document.querySelectorAll(".index-select").forEach(select => {
                select.innerHTML = '<option value="" disabled selected>Seleccione un índice...</option>';
                filteredIndices.forEach(index => {
                    let option = document.createElement("option");
                    option.value = index;
                    option.textContent = index;
                    select.appendChild(option);
                });
            });
        })
        .catch(error => {
            console.error("Error cargando índices:", error);
            document.querySelectorAll(".index-select").forEach(select => {
                select.innerHTML = "<option disabled>Error al cargar índices</option>";
            });
        });
});
