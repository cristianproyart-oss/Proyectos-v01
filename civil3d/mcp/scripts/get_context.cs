// get_context: resumen del documento activo. Se ejecuta en modo query (no cambia el dibujo).
// Cada dato va envuelto en T(...) para que un fallo de la API no tumbe todo el resumen.
// Si alguna firma no existe en tu versión, el error de compilación dirá la línea: corrígela con lookup_api.
int maxItems = 200;

object Selection()
{
    var r = ed.SelectImplied();
    if (r.Status != PromptStatus.OK || r.Value == null) return new object[0];
    return r.Value.GetObjectIds().Take(maxItems).Select(id =>
    {
        var e = tr.GetObject(id, OpenMode.ForRead) as Entity;
        return new { handle = id.Handle.ToString(), type = id.ObjectClass.DxfName, cls = e?.GetType().Name, layer = e?.Layer,
                     name = T(() => (string)e.GetType().GetProperty("Name")?.GetValue(e)) };
    }).ToList();
}

var uz = civ?.Settings?.DrawingSettings?.UnitZoneSettings;

var alignments = civ == null ? null : civ.GetAlignmentIds().Cast<ObjectId>().Take(maxItems).Select(id =>
{
    var a = (Alignment)tr.GetObject(id, OpenMode.ForRead);
    return new
    {
        name = a.Name, handle = id.Handle.ToString(),
        type = T(() => a.AlignmentType.ToString()),
        length = T(() => Math.Round(a.Length, 3)),
        start_station = T(() => Math.Round(a.StartingStation, 3)),
        end_station = T(() => Math.Round(a.EndingStation, 3)),
        site = T(() => a.SiteId.IsNull ? "(sin emplazamiento)" : ((Site)tr.GetObject(a.SiteId, OpenMode.ForRead)).Name),
        profiles = T(() => a.GetProfileIds().Cast<ObjectId>().Select(pid =>
        {
            var p = (Profile)tr.GetObject(pid, OpenMode.ForRead);
            return new { name = p.Name, type = p.ProfileType.ToString(),
                         start = T(() => Math.Round(p.StartingStation, 3)), end = T(() => Math.Round(p.EndingStation, 3)) };
        }).ToList())
    };
}).ToList();

var surfaces = civ == null ? null : civ.GetSurfaceIds().Cast<ObjectId>().Take(maxItems).Select(id =>
{
    var s = (Surface)tr.GetObject(id, OpenMode.ForRead);
    return new
    {
        name = s.Name, handle = id.Handle.ToString(), cls = s.GetType().Name,
        props = T(() => { var g = s.GetGeneralProperties();
                          return new { points = g.NumberOfPoints, zmin = Math.Round(g.MinimumElevation, 3), zmax = Math.Round(g.MaximumElevation, 3) }; }),
        out_of_date = T(() => Get(s, "IsOutOfDate"))
    };
}).ToList();

var corridors = civ == null ? null : civ.CorridorCollection.Cast<ObjectId>().Take(maxItems).Select(id =>
{
    var c = (Corridor)tr.GetObject(id, OpenMode.ForRead);
    return new
    {
        name = c.Name, handle = id.Handle.ToString(),
        out_of_date = T(() => c.IsOutOfDate),
        baselines = T(() => c.Baselines.Cast<Baseline>().Select(b => new
        {
            name = T(() => b.Name),
            alignment = T(() => ((Alignment)tr.GetObject(b.AlignmentId, OpenMode.ForRead)).Name),
            profile = T(() => ((Profile)tr.GetObject(b.ProfileId, OpenMode.ForRead)).Name),
            regions = T(() => b.BaselineRegions.Cast<BaselineRegion>().Select(r => new
            {
                name = r.Name, start = Math.Round(r.StartStation, 3), end = Math.Round(r.EndStation, 3),
                assembly = T(() => ((Assembly)tr.GetObject(r.AssemblyId, OpenMode.ForRead)).Name)
            }).ToList())
        }).ToList()),
        corridor_surfaces = T(() => c.CorridorSurfaces.Cast<CorridorSurface>().Select(cs => cs.Name).ToList())
    };
}).ToList();

var assemblies = civ == null ? null : civ.AssemblyCollection.Cast<ObjectId>().Take(maxItems).Select(id =>
{
    var a = (Assembly)tr.GetObject(id, OpenMode.ForRead);
    return new { name = a.Name, handle = id.Handle.ToString(),
                 groups = T(() => Items(Get(a, "Groups")).Select(g => Get(g, "Name")).ToList()) };
}).ToList();

var subassemblies = civ == null ? null : civ.SubassemblyCollection.Cast<ObjectId>().Take(maxItems).Select(id =>
{
    var s = (Subassembly)tr.GetObject(id, OpenMode.ForRead);
    return new { name = s.Name, handle = id.Handle.ToString(),
                 side = T(() => s.HasSide ? s.Side.ToString() : "(sin lado)")
               };
}).ToList();

return new
{
    autocad = new { version = Application.Version.ToString(), acadver = Application.GetSystemVariable("ACADVER"),
                    civil_api = typeof(CivilDocument).Assembly.GetName().Version?.ToString() },
    document = new { name = doc.Name, file = db.Filename, saved = !Convert.ToBoolean(Application.GetSystemVariable("DBMOD")),
                     insunits = db.Insunits.ToString(), measurement = db.Measurement.ToString() },
    civil = civ == null ? (object)"(CivilDocument no disponible: ¿es AutoCAD sin Civil?)" : new
    {
        drawing_units = T(() => uz.DrawingUnits.ToString()),
        angular_units = T(() => uz.AngularUnits.ToString()),
        coordinate_system = T(() => uz.CoordinateSystemCode),
        counts = new
        {
            alignments = alignments?.Count, surfaces = surfaces?.Count, corridors = corridors?.Count,
            assemblies = assemblies?.Count, subassemblies = subassemblies?.Count,
            sites = T(() => civ.GetSiteIds().Count), cogo_points = T(() => civ.CogoPoints.Count),
            point_groups = T(() => civ.PointGroups.Count)
        }
    },
    alignments, surfaces, corridors, assemblies, subassemblies,
    selection = T(Selection),
    note = "Listas limitadas a " + maxItems + " elementos por tipo."
};
