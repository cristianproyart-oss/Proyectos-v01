// Prueba final Parte 1 (run_query): alineamientos, superficies y corredores del dibujo activo.
var al = civ.GetAlignmentIds().Cast<ObjectId>().Select(id => (Alignment)tr.GetObject(id, OpenMode.ForRead))
            .Select(a => new { a.Name, longitud = Math.Round(a.Length, 2) }).ToList();
var su = civ.GetSurfaceIds().Cast<ObjectId>().Select(id => (Surface)tr.GetObject(id, OpenMode.ForRead))
            .Select(s => new { s.Name, tipo = s.GetType().Name }).ToList();
var co = civ.CorridorCollection.Cast<ObjectId>().Select(id => (Corridor)tr.GetObject(id, OpenMode.ForRead))
            .Select(c => new { c.Name, ejes = c.Baselines.Count }).ToList();
Console.WriteLine($"{al.Count} alineamientos, {su.Count} superficies, {co.Count} corredores");
return new { alineamientos = al, superficies = su, corredores = co };
