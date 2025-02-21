import re
from flask import Flask, render_template, request
from search import Search
import json
from openai import OpenAI
import os


# Obtener la clave de API y el modelo desde el .env
api_key = os.getenv("OPENAI_API_KEY")
MODELO = os.getenv("OPENAI_MODEL", "gpt-4o")  # Usa gpt-4o por defecto si no está definido
# Verificar que la clave de API esté presente
if not api_key:
    raise ValueError("La variable OPENAI_API_KEY no está definida en el archivo .env")
# Inicializa el cliente de OpenAI
client = OpenAI(api_key=api_key)



app = Flask(__name__)
es = Search()


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/")
def handle_search():
    query = request.form.get("query", "")
    index_name = request.form.get("index_name", "my_documents")  # Si no se selecciona, usa el predeterminado
    filters, parsed_query = extract_filters(query)
    from_ = request.form.get("from_", type=int, default=0)

    if parsed_query:
        search_query = {
            "must": {
                "multi_match": {
                    "query": parsed_query,
                    "fields": ["name", "summary", "content"],
                }
            }
        }
    else:
        search_query = {"must": {"match_all": {}}}

    results = es.search(
        index_name=index_name,
        query={"bool": {**search_query, **filters}},
        knn={
            "field": "embedding",
            "query_vector": es.get_embedding(parsed_query),
            "k": 10,
            "num_candidates": 50,
            **filters,
        },
        rank={"rrf": {}},
        aggs={
            "category-agg": {
                "terms": {
                    "field": "category.keyword",
                }
            },
            "year-agg": {
                "date_histogram": {
                    "field": "updated_at",
                    "calendar_interval": "year",
                    "format": "yyyy",
                },
            },
        },
        size=5,
        from_=from_,
    )
    aggs = {
        "Category": {
            bucket["key"]: bucket["doc_count"]
            for bucket in results["aggregations"]["category-agg"]["buckets"]
        },
        "Year": {
            bucket["key_as_string"]: bucket["doc_count"]
            for bucket in results["aggregations"]["year-agg"]["buckets"]
            if bucket["doc_count"] > 0
        },
    }
    return render_template(
        "index.html",
        results=results["hits"]["hits"],
        query=query,
        from_=from_,
        total=results["hits"]["total"]["value"],
        aggs=aggs,
        selected_index=index_name
    )



@app.get("/document/<id>")
def get_document(id):
    document = es.retrieve_document(id)
    title = document["_source"]["name"]
    paragraphs = document["_source"]["content"].split("\n")
    return render_template("document.html", title=title, paragraphs=paragraphs)


@app.cli.command()
def reindex():
    """Regenerate the Elasticsearch index."""
    response = es.reindex()
    print(
        f'Index with {len(response["items"])} documents created '
        f'in {response["took"]} milliseconds.'
    )


@app.cli.command()
def deploy_elser():
    """Deploy the ELSER v2 model to Elasticsearch."""
    try:
        es.deploy_elser()
    except Exception as exc:
        print(f"Error: {exc}")
    else:
        print(f"ELSER model deployed.")


def extract_filters(query):
    filter_regex = r"category:([^\s]+)\s*"
    m = re.search(filter_regex, query)
    if m is None:
        return {}, query  # no filters
    filters = {"filter": [{"term": {"category.keyword": {"value": m.group(1)}}}]}
    query = re.sub(filter_regex, "", query).strip()
    return filters, query

@app.post("/create_index")
def create_index():
    index_name = request.form.get("index_name", "").strip()
    print(f"📌 Intentando crear el índice: {index_name}")  # Debugging

    if not index_name:
        print("⚠ No se proporcionó un nombre de índice")
        return "Debe proporcionar un nombre de índice.", 400
    
    try:
        es.create_index(index_name)  # Llamamos a la función en `search.py`
        print(f"✅ Índice '{index_name}' creado exitosamente.")
        return f"Índice '{index_name}' creado exitosamente.", 200
    except Exception as e:
        print(f"❌ Error al crear el índice: {str(e)}")
        return f"Error al crear el índice: {str(e)}", 500





@app.post("/upload_json")
def upload_json():
    if "file" not in request.files:
        return "No se envió ningún archivo.", 400

    file = request.files["file"]
    index_name = request.form.get("index_name", "").strip()
    
    if not index_name:
        return "Debe seleccionar un índice.", 400

    if file.filename == "":
        return "No se seleccionó ningún archivo.", 400

    if not file.filename.endswith(".json"):
        return "Solo se permiten archivos JSON.", 400

    try:
        documents = json.load(file)
        if not isinstance(documents, list):
            return "El archivo JSON debe contener un array de documentos.", 400

        es.insert_documents(documents, index_name)  # Inserta documentos en el índice seleccionado
        
        return f"Se cargaron {len(documents)} documentos correctamente en el índice '{index_name}'.", 200

    except Exception as e:
        return f"Error procesando el archivo: {str(e)}", 500


@app.post("/rag")
def rag():
    query = request.form.get("query", "").strip()
    index_name = request.form.get("index_name", "my_documents") 
    if not query:
        return "Debe proporcionar una consulta.", 400

    # Usar la búsqueda existente para recuperar documentos
    filters, parsed_query = extract_filters(query)
    from_ = 0  # Siempre comenzamos desde el primer resultado
    
    results = es.search(
        index_name=index_name,
        query={"bool": {"must": {"multi_match": {"query": parsed_query, "fields": ["name", "summary", "content"]}}}},
        knn={
            "field": "embedding",
            "query_vector": es.get_embedding(parsed_query),
            "k": 5,  # Número de documentos relevantes a recuperar
            "num_candidates": 50,
            **filters,
        },
        size=5
    )

    # Extraer contenido de los documentos recuperados
    if "hits" in results and "hits" in results["hits"]:
        context = "\n\n".join([hit["_source"]["content"] for hit in results["hits"]["hits"]])
    else:
        context = "No se encontraron documentos relevantes."

    # Generar respuesta con OpenAI
    response = client.chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": "Responde la pregunta utilizando la siguiente información recuperada."},
            {"role": "user", "content": f"Contexto:\n{context}\n\nPregunta: {query}"}
        ]
    )

    return response.choices[0].message.content


@app.get("/config")
def config():
    try:
        indices = es.get_indices()  # Obtiene la lista de índices
        print("Índices en config.html:", indices)  # Depuración
    except Exception as e:
        indices = []
        print("Error al obtener índices en config:", e)
    return render_template("config.html", indices=indices)

@app.get("/get_indices")
def get_indices():
    try:
        indices = es.get_indices()  # Obtiene todos los índices
        filtered_indices = [index for index in indices if not index.startswith(".")]  # Filtrar índices del sistema
        return filtered_indices  # Devuelve solo los índices creados por el usuario
    except Exception as e:
        print("Error al obtener índices:", e)
        return []





if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
