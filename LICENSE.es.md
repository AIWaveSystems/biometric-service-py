# Licencia MIT — traducción informativa al español

> **Aviso importante.** Esta traducción se ofrece **solo para facilitar la
> comprensión**. No tiene valor legal. El único texto vinculante es la versión en
> inglés del archivo [`LICENSE`](LICENSE). Ante cualquier discrepancia entre
> ambos textos, prevalece el inglés.

---

Copyright (c) 2026 Ilesandres

Por la presente se concede permiso, libre de cargo, a cualquier persona que
obtenga una copia de este software y de los archivos de documentación asociados
(el "Software"), para utilizar el Software sin restricción, incluyendo sin
limitación los derechos a usar, copiar, modificar, fusionar, publicar,
distribuir, sublicenciar y/o vender copias del Software, y a permitir a las
personas a las que se les proporcione el Software a hacer lo mismo, sujeto a las
siguientes condiciones:

El aviso de copyright anterior y este aviso de permiso deberán incluirse en
todas las copias o partes sustanciales del Software.

EL SOFTWARE SE PROPORCIONA "TAL CUAL", SIN GARANTÍA DE NINGÚN TIPO, EXPRESA O
IMPLÍCITA, INCLUYENDO PERO NO LIMITÁNDOSE A LAS GARANTÍAS DE COMERCIABILIDAD,
IDONEIDAD PARA UN PROPÓSITO PARTICULAR Y NO INFRACCIÓN. EN NINGÚN CASO LOS
AUTORES O TITULARES DEL COPYRIGHT SERÁN RESPONSABLES DE NINGUNA RECLAMACIÓN,
DAÑO U OTRA RESPONSABILIDAD, YA SEA EN UNA ACCIÓN CONTRACTUAL, EXTRACONTRACTUAL
O DE CUALQUIER OTRO TIPO, DERIVADA DE, RELACIONADA CON O EN CONEXIÓN CON EL
SOFTWARE O SU USO U OTRAS OPERACIONES CON EL SOFTWARE.

---

## Qué significa esto en la práctica

| Puedes | Debes | No hay |
| --- | --- | --- |
| Usarlo con **fines comerciales**, sin pagar nada | Conservar el aviso de copyright y esta licencia en las copias o partes sustanciales | Garantía de ningún tipo |
| Modificarlo y adaptarlo a lo que necesites | | Responsabilidad del autor por daños |
| Redistribuirlo, con o sin cambios | | Obligación de publicar tus modificaciones |
| Sublicenciarlo o venderlo | | Soporte garantizado |
| Usarlo en software cerrado y propietario | | |

### La mención al autor

La licencia MIT **ya exige la atribución**: conservar el aviso de copyright es
una condición obligatoria, no una cortesía. Quien redistribuya este software,
lo use comercialmente o lo integre en un producto cerrado, debe mantener el
aviso `Copyright (c) 2026 Ilesandres` accesible: en un archivo de licencias, en
una pantalla de "Acerca de", en la documentación, o donde corresponda según el
formato del producto.

Si además quieres citarlo, esta forma es suficiente:

```
Construido sobre Login Biométrico Service
https://github.com/AIWaveSystems/biometric-service-py
Copyright (c) 2026 Ilesandres — Licencia MIT
```

### Bajo tu propia responsabilidad

Los dos párrafos en mayúsculas son la parte que más importa en un proyecto como
este. El software se entrega **tal cual**, sin garantías, y el autor **no
responde** por ningún daño derivado de su uso.

!!! Esto es especialmente relevante aquí
    Este servicio trata datos biométricos y toma decisiones de autenticación. Sus
    umbrales **no están calibrados** contra una población real de impostores, y
    tiene limitaciones conocidas y documentadas que afectan a la seguridad.

    Quien lo despliegue asume la responsabilidad de validarlo para su caso,
    calibrar los umbrales con su propia población, y cumplir la normativa de
    protección de datos que le aplique (en Colombia, la Ley 1581 de 2012).

    Lee las [limitaciones conocidas](docs/operacion/limitaciones.md) **antes** de
    usarlo en producción.

---

## Componentes de terceros

Este proyecto usa modelos y bibliotecas con sus propias licencias, que debes
respetar además de la MIT. Están detalladas en [`NOTICE`](NOTICE).
