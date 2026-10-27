# 9. Docker para principiantes

## ¿Para qué se usa?

Docker Desktop ejecuta PostgreSQL en un contenedor aislado. Python, Streamlit y Ollama siguen ejecutándose directamente en Windows. El volumen `postgres_datos` conserva la información aunque se detenga o quite el contenedor.

## El archivo `docker-compose.yml`

- `image: postgres:15`: usa PostgreSQL 15.
- `container_name`: identifica el contenedor en Docker Desktop.
- `restart: unless-stopped`: lo reinicia si Docker vuelve a iniciar, salvo que se haya detenido manualmente.
- `environment`: crea la base, el usuario y la clave iniciales desde variables del `.env`.
- `ports`: publica el puerto del contenedor 5432 como `POSTGRES_HOST_PORT` en Windows; el valor recomendado es 5433 para no chocar con PostgreSQL local en 5432.
- `volumes`: persiste los archivos de PostgreSQL en el volumen `postgres_datos`.
- `healthcheck`: verifica que PostgreSQL responda.

## Comandos en PowerShell

Desde la raíz del proyecto:

```powershell
docker compose up -d
docker compose ps
docker compose logs -f postgres
docker compose stop
docker compose down
```

`up -d` inicia PostgreSQL en segundo plano; `ps` muestra estado; `logs -f` sigue los registros (pulsa `Ctrl+C` para dejar de verlos); `stop` detiene el contenedor conservándolo; `down` elimina el contenedor y la red, pero conserva el volumen.

El comando siguiente también borra el volumen y los datos de PostgreSQL. Úsalo solo si de verdad quieres empezar la base del contenedor desde cero:

```powershell
docker compose down -v
```

## Conexión desde pgAdmin

Registra un servidor con host `localhost`, puerto `5433`, base `simulador-trading-demo` (o el valor de `DB_NAME`), y el usuario y la contraseña configurados en `.env`. Si usas el servidor local, el puerto habitual de este proyecto es `5432`.

Para `psql`, si está instalado pero no está en `PATH`, ejecuta el binario desde una ruta de PostgreSQL instalada. Ejemplo para la versión 15:

```powershell
& 'C:\Program Files\PostgreSQL\15\bin\psql.exe' -h localhost -p 5433 -U simulador -d simulador-trading-demo
```

Sustituye usuario, base, puerto y ruta según tu instalación. También puedes ejecutar scripts SQL con Query Tool de pgAdmin.

## Usar PostgreSQL local en vez del contenedor

En `.env`, configura `DB_HOST=localhost` y `DB_PORT=5432`. No es necesario iniciar Docker para usar PostgreSQL local. Si eliges Docker, configura `DB_PORT=5433` y `POSTGRES_HOST_PORT=5433`, y arranca el servicio con `docker compose up -d`.

La aplicación busca `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` y `DB_PASSWORD`. Compose usa `DB_NAME`, `DB_USER`, `DB_PASSWORD` y `POSTGRES_HOST_PORT` para el contenedor.

## Problemas frecuentes

- **Puerto ocupado:** usa 5433 para el contenedor y confirma que `DB_PORT` tenga ese mismo valor.
- **Docker Desktop apagado:** abre Docker Desktop y espera a que indique que el motor está activo.
- **Clave incorrecta:** `.env` y el volumen inicializado deben coincidir. Cambiar la clave del `.env` no cambia automáticamente la de una base persistida.
- **No persisten los datos:** confirma que el volumen siga presente; `docker compose down` lo conserva y `down -v` lo elimina.
- **No se puede crear la DB desde la app:** el usuario debe tener permiso `CREATEDB` en PostgreSQL. Si no lo tiene, crea `simulador-trading-demo` en pgAdmin y luego vuelve a la app.
