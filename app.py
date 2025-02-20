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
    if not index_name:
        return "Debe proporcionar un nombre de índice.", 400
    
    try:
        es.create_index(index_name)  # Llamamos la función en search.py
        return f"Índice '{index_name}' creado exitosamente.", 200
    except Exception as e:
        return f"Error al crear el índice: {str(e)}", 500




@app.post("/upload_json")
def upload_json():
    if "file" not in request.files:
        return "No se envió ningún archivo.", 400

    file = request.files["file"]
    
    if file.filename == "":
        return "No se seleccionó ningún archivo.", 400

    if not file.filename.endswith(".json"):
        return "Solo se permiten archivos JSON.", 400

    try:
        # Leer el contenido del archivo JSON
        documents = json.load(file)

        # Verificar si es una lista de documentos
        if not isinstance(documents, list):
            return "El archivo JSON debe contener un array de documentos.", 400

        # Insertar documentos en Elasticsearch
        es.insert_documents(documents)
        
        return f"Se cargaron {len(documents)} documentos correctamente.", 200

    except Exception as e:
        return f"Error procesando el archivo: {str(e)}", 500



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
