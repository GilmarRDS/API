# 📋 Regras de Alocação Implementadas

Este documento explica todas as regras que o sistema segue ao alocar professores e gerar horários.

## ✅ Regras Implementadas

### 1. **REGRA DE CONFLITO DE HORÁRIO** ✅
**Descrição:** Um professor não pode estar em mais de uma turma no mesmo horário (fisicamente impossível)

**Como funciona:**
- O sistema verifica se o professor já está ocupado no slot (horário) solicitado
- Se estiver ocupado, o professor não pode ser alocado
- **Arquivo:** `regras_alocacao.py` → `REGRA_CONFLITO_HORARIO`

---

### 2. **REGRA DE REGIÕES** ✅
**Descrição:** Professores devem respeitar limites de região

**Regras específicas:**
- **Praia Grande** ❌ NÃO pode dar aula em **Fundão** e **Timbuí**
- **Fundão** ❌ NÃO pode dar aula em **Praia Grande**
- **Timbuí** ❌ NÃO pode dar aula em **Praia Grande**
- **Fundão** ✅ PODE dar aula em **Timbuí** (em último caso)
- **Timbuí** ✅ PODE dar aula em **Fundão** (em último caso)
- **Preferência:** Sempre priorizar a região do professor

**Como funciona:**
- Mesma região = Prioridade 100 (máxima)
- Região compatível = Prioridade 50 (média)
- Região incompatível = Prioridade 0 (bloqueado)
- **Arquivo:** `regras_alocacao.py` → `verificar_compatibilidade_regiao()`

---

### 3. **REGRA DE TURNOS** ✅
**Descrição:** Professor pode dar aula em mais de um turno

**Como funciona:**
- Professores podem ser alocados em MATUTINO, VESPERTINO ou ambos
- Apenas professores com `TURNO_FIXO` configurado têm restrição
- **Arquivo:** `regras_alocacao.py` → `REGRA_TURNOS`

---

### 4. **REGRA DE JANELAS/BURACOS** ✅
**Descrição:** Não pode ter janelas/buracos entre as aulas

**Como funciona:**
- Na mesma escola: aulas devem ser consecutivas (sem buracos)
- Na mesma rota: aulas devem ser consecutivas (sem buracos)
- Escolas diferentes (sem rota): pode ter buracos (não é problema)
- **Arquivo:** `regras_alocacao.py` → `verificar_janelas()`

**Exemplo:**
- ✅ Permitido: 1ª aula, 2ª aula, 3ª aula (consecutivo)
- ❌ Bloqueado: 1ª aula, 3ª aula (buraco na 2ª)
- ✅ Permitido: Escola A (1ª aula), Escola B (3ª aula) - se não estiverem na mesma rota

---

### 5. **REGRA LDB - CÁLCULO DE PL** ✅
**Descrição:** Seguir LDB: 1/3 de PL (Planejamento) para cada carga de aulas

**Fórmula:**
```
PL = AULAS / 3
Carga Total = AULAS + PL
```

**Exemplos:**
- 20 aulas → 7 PL → Total: 27 aulas
- 30 aulas → 10 PL → Total: 40 aulas
- 15 aulas → 5 PL → Total: 20 aulas

**Como funciona:**
- O sistema calcula automaticamente o PL ao criar/atualizar professores
- PL é arredondado para cima (mínimo 1)
- **Arquivo:** `regras_alocacao.py` → `calcular_pl_ldb()`

---

### 6. **REGRA DE LIMITES DE CARGA HORÁRIA** ✅
**Descrição:** Limites de carga horária para professores

**Limites:**
- **Máximo:** 30 aulas
- **Mínimo:** 14 aulas
- **Exceção:** Se o quantitativo disponível for menor que 14, permite valores menores

**Como funciona:**
- Sistema valida carga antes de criar/atualizar professores
- Bloqueia cargas acima de 30 aulas
- Permite cargas abaixo de 14 apenas se necessário
- **Arquivo:** `regras_alocacao.py` → `verificar_limites_carga()`

---

### 7. **REGRA DE DISTRIBUIÇÃO INTELIGENTE** ✅
**Descrição:** Distribuir carga de forma inteligente e equilibrada

**Objetivos:**
- Distribuir aulas de forma equilibrada entre professores
- Preferir cargas "cheias" (20, 25, 30 aulas)
- Respeitar limites mínimo e máximo
- Otimizar número de professores necessários

**Como funciona:**
- Calcula número ideal de professores baseado na média alvo (20 aulas)
- Distribui carga respeitando limites
- Prefere cargas de 20, 25 ou 30 aulas quando possível
- **Arquivo:** `regras_alocacao.py` → `distribuir_carga_inteligente()`

**Exemplo:**
- 60 aulas disponíveis → 3 professores com 20 aulas cada (ideal)
- 45 aulas disponíveis → 2 professores com 20 e 25 aulas
- 100 aulas disponíveis → 4 professores (30+25+25+20)

---

## 🔄 Como o Sistema Aplica as Regras

### Durante a Alocação (resolver_grade_inteligente):

1. **Para cada aula a ser alocada:**
   - Busca professores que lecionam a matéria
   - Verifica turno fixo (se aplicável)
   - ✅ Verifica compatibilidade de região
   - ✅ Verifica limite de carga horária
   - ✅ Verifica conflito de horário (mesmo slot)
   - ✅ Verifica janelas/buracos
   - Calcula score de prioridade
   - Escolhe o melhor candidato

2. **Score de Prioridade:**
   - Professor EFETIVO na escola base: +100.000 pontos
   - Mesma região: +100 pontos
   - Região compatível: +50 pontos
   - Escola base: +2.000 pontos
   - Escola já visitada: +1.000 pontos
   - Carga disponível: +10 pontos por aula disponível
   - Aulas consecutivas: +500 pontos

### Ao Criar Novos Professores:

1. **Distribuição Inteligente:**
   - Calcula quantos professores são necessários
   - Distribui carga respeitando limites (14-30 aulas)
   - Prefere cargas cheias (20, 25, 30)

2. **Cálculo de PL:**
   - Calcula PL automaticamente (1/3 da carga)
   - Salva no campo `QTD_PL`

3. **Validação:**
   - Verifica se carga está dentro dos limites
   - Permite valores menores apenas se necessário

---

## 📁 Arquivos Relacionados

- **`regras_alocacao.py`** - Todas as regras e funções de validação
- **`app.py`** - Aplicação das regras na alocação
- **`config.py`** - Configurações gerais do sistema

---

## 🧪 Como Testar

1. **Teste de Região:**
   - Crie um professor de Praia Grande
   - Tente alocar em escola de Fundão
   - ✅ Deve ser bloqueado

2. **Teste de Janelas:**
   - Aloque professor na 1ª aula de uma escola
   - Tente alocar na 3ª aula da mesma escola
   - ✅ Deve ser bloqueado (buraco na 2ª)

3. **Teste de PL:**
   - Crie professor com 20 aulas
   - ✅ PL deve ser 7 (20/3 = 6.67 → 7)

4. **Teste de Limites:**
   - Tente criar professor com 35 aulas
   - ✅ Deve ser bloqueado (máximo 30)

---

## 📝 Notas Importantes

- Todas as regras são **obrigatórias** e não podem ser ignoradas
- O sistema prioriza sempre a melhor alocação possível
- Professores criados automaticamente são sempre DT (Designado Temporário)
- PL é calculado automaticamente e não precisa ser informado manualmente
