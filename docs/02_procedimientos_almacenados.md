Los procedimientos están en `sql/02_procedures.sql`. Su responsabilidad es
mantener el efectivo, las posiciones y las órdenes coherentes dentro de una
operación de compra o venta.

## Precio y valoración

`sp_registrar_compra` y `sp_registrar_venta` reciben agente, ticker, cantidad y
fecha. Buscan el cierre de esa fecha en `precios_historicos`; Python no les envía
un precio negociable.

`fn_valor_portafolio(agente, fecha)` suma efectivo y valor de mercado de las
posiciones. Si falta el precio de alguna posición para la fecha solicitada,
genera un error para impedir snapshots incompletos.

## Compra

1. Comprueba que la cantidad sea positiva y que exista el precio.
2. Bloquea la fila del portafolio con `FOR UPDATE`.
3. Lee comisión y límite de concentración.
4. Comprueba saldo suficiente.
5. Calcula el valor de la cartera y verifica que la posición tras la compra no
   exceda el 30% del valor posterior a la comisión.
6. Descuenta importe y comisión, actualiza cantidad y costo promedio e inserta
   una orden ejecutada.

El costo promedio ponderado usa el precio de compra y las cantidades. La
comisión afecta al efectivo, pero no al costo promedio de las acciones.

## Venta

1. Comprueba cantidad positiva y precio disponible.
2. Bloquea portafolio y posición.
3. Rechaza ventas superiores a la posición disponible; no se permiten ventas en
   corto.
4. Abona el importe neto de comisión y reduce o elimina la posición.
5. Inserta la orden ejecutada.

## Transacciones y errores

PostgreSQL ejecuta cada `CALL` dentro de la transacción de la sesión. Si una
validación lanza `RAISE EXCEPTION`, la llamada no conserva sus cambios. Los
bloqueos evitan que dos operaciones simultáneas del mismo agente usen el mismo
saldo o posición sin coordinarse. Esto ayuda a preservar atomicidad y
consistencia; la durabilidad corresponde a PostgreSQL una vez confirmado el
commit.

Las operaciones rechazadas no crean órdenes ejecutadas. El motor de Python
registrará el resultado y el motivo en `decisiones_agentes`.

## Snapshot y vista

`sp_tomar_snapshot(fecha)` recorre agentes activos con portafolio y crea o
actualiza su snapshot para ese día. `vw_metricas_finales` ofrece una primera
comparación a partir del último snapshot; las métricas de serie temporal se
completan en la fase 4.

## Pruebas

`sql/03_tests.sql` crea un escenario temporal y cubre:

- Compra válida y venta válida.
- Compra rechazada por saldo insuficiente.
- Venta rechazada sin posición.

El archivo termina con `ROLLBACK`, por lo que sus datos de prueba no quedan
guardados. 