import json
from pprint import pprint
import os
import time

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer

load_dotenv()


class Search:
    def __init__(self):
        while True:  # Bucle infinito hasta que se conecte
            try:
                self.model = SentenceTransformer("all-MiniLM-L6-v2")
                # self.es = Elasticsearch(
                #     cloud_id=os.environ["ELASTIC_CLOUD_ID"],
                #     api_key=os.environ["ELASTIC_API_KEY"],
                # )
                self.es = Elasticsearch(
                    # Si es corre con docker poner:hosts=["http://elasticsearch-goornella:9200"], 
                    # Si es corro con python -m flask run --host=0.0.0.0 --port=5001 poner hosts=["http://localhost:9200"],
                    hosts=["http://localhost:9200"], 
                    verify_certs=False
                )  
                client_info = self.es.info()
                print("Connected to Elasticsearch!")
                pprint(client_info.body)
                break  # Salir del bucle si la conexión es exitosa

            except Exception as e:
                print("❌ Elasticsearch no disponible, reintentando en 5 segundos...")
                time.sleep(5)  # Esperar 5 segundos antes de intentar de nuevo

    def get_indices(self):
        try:
            indices = list(self.es.indices.get_alias().keys())  # Obtener los nombres de los índices
            print("Índices encontrados:", indices)  # Para depuración
            return indices
        except Exception as e:
            print("Error al obtener los índices:", e)
            return []



    def create_index(self, index_name):
        print(f"🔍 Creando índice en Elasticsearch: {index_name}")  # Debugging
        self.es.indices.delete(index=index_name, ignore_unavailable=True)
        self.es.indices.create(
            index=index_name,
            body={
                "mappings": {
                    "properties": {
                        "embedding": {
                            "type": "dense_vector",
                            "dims": 384,  # Ajusta según el modelo
                            "index": True,
                            "similarity": "l2_norm"
                        }
                    }
                }
            }
        )


    def get_embedding(self, text):
        return self.model.encode(text)

    def insert_document(self, document,index_name="my_documents"):
        return self.es.index(
            index=index_name,
            document={
                **document,
                "embedding": self.get_embedding(document["summary"]),
            },
        )

    def insert_documents(self, documents,index_name="my_documents"):
        operations = []
        for document in documents:
            operations.append({"index": {"_index": index_name}})
            operations.append(
                {
                    **document,
                    "embedding": self.get_embedding(document["summary"]),
                }
            )

        response = self.es.bulk(operations=operations)
        
        # Convierte la respuesta a un diccionario antes de imprimir
        #print("Bulk Insert Response:", response.body)  
        return response



    def reindex(self):
        self.create_index()
        with open("data.json", "rt") as f:
            documents = json.loads(f.read())
        return self.insert_documents(documents)

    def search(self, index_name="my_documents", **query_args):
        #print("Query Args:", query_args)  # Depuración

        # Eliminar `sub_searches` ya que no es un argumento válido
        query_args.pop("sub_searches", None)

        # Eliminar `rank` si contiene `rrf`, ya que no es compatible con licencia básica
        if "rank" in query_args and "rrf" in query_args["rank"]:
            del query_args["rank"]

        return self.es.search(
            index=index_name,
            **query_args
        )



    def retrieve_document(self, id):
        return self.es.get(index="my_documents", id=id)

    def deploy_elser(self):
        # download ELSER v2
        self.es.ml.put_trained_model(
            model_id=".elser_model_2", input={"field_names": ["text_field"]}
        )

        # wait until ready
        while True:
            status = self.es.ml.get_trained_models(
                model_id=".elser_model_2", include="definition_status"
            )
            if status["trained_model_configs"][0]["fully_defined"]:
                # model is ready
                break
            time.sleep(1)

        # deploy the model
        self.es.ml.start_trained_model_deployment(model_id=".elser_model_2")

        # define a pipeline
        self.es.ingest.put_pipeline(
            id="elser-ingest-pipeline",
            processors=[
                {
                    "inference": {
                        "model_id": ".elser_model_2",
                        "input_output": [
                            {
                                "input_field": "summary",
                                "output_field": "elser_embedding",
                            }
                        ],
                    }
                }
            ],
        )
