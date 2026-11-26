// Prueba de run_modify. ÚSALO SOLO EN UNA COPIA DEL DWG.
// Añade un MText en el espacio modelo con la fecha, en la capa actual. Se deshace con U / DESHACER.
if (!db.Filename.Contains("_prueba", StringComparison.OrdinalIgnoreCase))
    return "Parado: el archivo no parece una copia de prueba (su nombre no contiene '_prueba'). " + db.Filename;
var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite);
var t = new MText { Contents = "Civil3DAgent: prueba run_modify " + DateTime.Now.ToString("yyyy-MM-dd HH:mm"),
                    Location = new Autodesk.AutoCAD.Geometry.Point3d(0, 0, 0), TextHeight = 2.5 };
ms.AppendEntity(t);
tr.AddNewlyCreatedDBObject(t, true);
return "MText creado con handle " + t.Handle;
