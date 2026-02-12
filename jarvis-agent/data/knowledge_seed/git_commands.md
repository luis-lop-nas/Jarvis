# Git - Comandos Esenciales

## Configuración inicial
```bash
git config --global user.name "Tu Nombre"
git config --global user.email "tu@email.com"
```

## Crear repositorio
```bash
git init                    # Inicializar repo
git clone URL              # Clonar repo existente
```

## Comandos básicos
```bash
git status                 # Ver estado
git add archivo.txt        # Añadir archivo
git add .                  # Añadir todos los archivos
git commit -m "mensaje"    # Crear commit
git push origin main       # Subir cambios
git pull                   # Bajar cambios
```

## Ramas (branches)
```bash
git branch                 # Listar ramas
git branch nombre          # Crear rama
git checkout nombre        # Cambiar a rama
git checkout -b nombre     # Crear y cambiar
git merge nombre           # Fusionar rama
git branch -d nombre       # Eliminar rama
```

## Historial
```bash
git log                    # Ver commits
git log --oneline          # Versión compacta
git diff                   # Ver cambios
git show commit_id         # Ver commit específico
```

## Deshacer cambios
```bash
git checkout -- archivo    # Descartar cambios
git reset HEAD archivo     # Unstage archivo
git reset --hard HEAD      # Resetear todo
git revert commit_id       # Revertir commit
```

## Stash (guardar temporalmente)
```bash
git stash                  # Guardar cambios
git stash list             # Listar stashes
git stash apply            # Aplicar último stash
git stash pop              # Aplicar y eliminar
```

## Remoto
```bash
git remote -v              # Ver remotos
git remote add origin URL  # Añadir remoto
git fetch                  # Traer cambios sin merge
```

## Tags
```bash
git tag v1.0.0             # Crear tag
git tag                    # Listar tags
git push origin v1.0.0     # Subir tag
```
