import requests
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
import json
from sqlalchemy import create_engine, Column, Integer, String, Float, Date
from datetime import date, datetime
from pydantic import BaseModel, model_validator, Field

# --- Configuração do Banco de Dados (SQLite com SQLAlchemy) ---
DATABASE_URL = 'sqlite:///./DB/mangadb.sqlite3'

engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Manga(Base):
    __tablename__ = 'mangas'
    id = Column(Integer, primary_key=True, index=True)
    id_api = Column(Integer, index=True)
    name = Column(String, index=True)
    chapters = Column(Integer, nullable=False, server_default='0')
    cover_url = Column(String)
    type = Column(String)
    status = Column(String)
    start_date = Column(Date, nullable=True)
    finish_date = Column(Date, nullable=True)
    score = Column(Float, nullable=True)
    rank = Column(Integer)
    popularity = Column(Integer)
    chapters_read = Column(Integer, nullable=False, server_default='0')

# Cria a tabela no banco de dados, se ela não existir
Base.metadata.create_all(bind=engine)

# Função para obter uma sessão do banco de dados
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Configuração do FastAPI ---
app = FastAPI()
templates = Jinja2Templates(directory='templates')

# URL da API externa que vamos usar
JIKAN_API_URL = "https://api.jikan.moe/v4/manga"

# --- Modelos Pydantic para validação ---
# Este modelo define como serão os dados que o frontend enviará para salvar um mangá
class MangaCreate(BaseModel):
    id_api: int
    name: str
    cover_url: str
    chapters: int |  None = Field(default=None, ge=0)
    type: str
    status: str
    score: float | None
    rank: int | None
    popularity: int | None
    start_date: date | None = None 
    finish_date: date | None = None
    chapters_read: int = Field(default=0, ge=0)

    # VALIDADOR:
    @model_validator(mode='after')
    def check_chapters_read_not_greater_than_total(self) -> 'MangaCreate':
        """Valida se os capítulos lidos não excedem o total de capítulos."""
        chapters_read = self.chapters_read
        total_chapters = self.chapters
        
        #Ajuste na lógica: a validação deve ocorrer sempre que o total_chapters for um número (incluindo 0)
        if total_chapters is not None and chapters_read is not None:
            if chapters_read > total_chapters:
                raise ValueError('A quantidade de capítulos lidos não pode ser maior que o total de capítulos.')
        
        return self

# --- Rotas da Aplicação ---
@app.get('/')
def read_root(request: Request, db: Session = Depends(get_db)):
    """
    Rota principal: Exibe a página HTML com o formulário de cadastro e a lista de mangás já salvos no banco de dados.
    """
    mangas_cadastrados = db.query(Manga).all()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "mangas": mangas_cadastrados
    })

def parse_date_from_string(date_str: str):
    if not date_str:
        return None
    try:
        # Tenta converter do formato YYYY-MM-DD que vem do formulário HTML
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

@app.post("/api/buscar-manga")
def api_buscar_manga(manga_name: str = Form(...)):
    """
    Busca até 15 mangás na API Jikan e retorna os dados em formato JSON.
    Não interage com o banco de dados.
    """
    print(f"Buscando API por: {manga_name}")
    search_response = requests.get(f"{JIKAN_API_URL}?q={manga_name}&limit=15")
    
    if search_response.status_code != 200 or not search_response.json().get('data'):
        raise HTTPException(status_code=404, detail="Nenhum mangá encontrado com esse nome.")

    # Retorna a lista completa de dados
    manga_list = search_response.json()['data']
    return JSONResponse(content=manga_list)

# NOVA ROTA: BUSCAR DETALHES COMPLETOS POR ID
@app.get("/api/manga/{manga_id}")
def api_get_manga_details(manga_id: int):
    """
    Busca os detalhes completos de um único mangá pelo seu ID da API Jikan.
    """
    full_response = requests.get(f"{JIKAN_API_URL}/{manga_id}/full")
    if full_response.status_code != 200 or not full_response.json().get('data'):
        raise HTTPException(status_code=404, detail="Não foi possível obter os detalhes completos do mangá.")
        
    data_full = full_response.json().get('data')
    return JSONResponse(content=data_full)
    
# NOVA ROTA DE API: SALVAR O MANGÁ RECEBENDO JSON
@app.post("/api/salvar-manga")
def api_salvar_manga(manga_data: MangaCreate, db: Session = Depends(get_db)):
    """
    Recebe os dados do mangá (validados pelo Pydantic) e salva no banco.
    """
    # Checa se o mangá já existe
    manga_existente = db.query(Manga).filter(Manga.id_api == manga_data.id_api).first()
    if manga_existente:
        raise HTTPException(status_code=409, detail="Este mangá já está cadastrado.")

    # Cria o novo objeto usando os dados do modelo Pydantic
    novo_manga = Manga(
        id_api=manga_data.id_api,
        name=manga_data.name,
        chapters=manga_data.chapters,
        cover_url=manga_data.cover_url,
        type=manga_data.type,
        status=manga_data.status,
        score=manga_data.score,
        rank=manga_data.rank,
        popularity=manga_data.popularity,
        start_date=manga_data.start_date,
        finish_date=manga_data.finish_date,
        chapters_read=manga_data.chapters_read
    )
    db.add(novo_manga)
    db.commit()
    
    return {"status": "sucesso", "message": f"Mangá '{novo_manga.name}' salvo!"}

@app.get("/manga/edit/{manga_id}", response_class=HTMLResponse)
def get_edit_manga_page(request: Request, manga_id: int, db: Session = Depends(get_db)):
    """Busca um mangá pelo seu ID no nosso banco e renderiza a página de edição."""
    manga = db.query(Manga).filter(Manga.id == manga_id).first()
    if not manga:
        raise HTTPException(status_code=404, detail="Mangá não encontrado no seu banco de dados.")
    
    return templates.TemplateResponse("edit_manga.html", {"request": request, "manga": manga})

@app.post("/manga/update/{manga_id}")
def update_manga_chapters(manga_id: int, chapters_read: int = Form(...), db: Session = Depends(get_db)):
    """Atualiza o número de capítulos lidos de um mangá específico."""
    manga = db.query(Manga).filter(Manga.id == manga_id).first()
    if not manga:
        raise HTTPException(status_code=404, detail="Mangá não encontrado.")

    # Reaplicamos a validação para segurança
    if chapters_read < 0:
        # Idealmente, retorne uma mensagem de erro para o usuário
        print("Erro: Capítulos lidos não pode ser negativo.")
        return RedirectResponse(url=f"/manga/edit/{manga_id}", status_code=303)
        
    if manga.chapters is not None and chapters_read > manga.chapters:
        print("Erro: Capítulos lidos não pode exceder o total.")
        return RedirectResponse(url=f"/manga/edit/{manga_id}", status_code=303)

    manga.chapters_read = chapters_read
    db.commit()

    # Redireciona de volta para a página inicial
    return RedirectResponse(url="/", status_code=303)

@app.post("/manga/delete/{manga_id}")
def delete_manga(manga_id: int, db: Session = Depends(get_db)):
    """Deleta um mangá do banco de dados."""
    manga = db.query(Manga).filter(Manga.id == manga_id).first()
    if not manga:
        raise HTTPException(status_code=404, detail="Mangá não encontrado.")

    db.delete(manga)
    db.commit()

    return RedirectResponse(url="/", status_code=303)