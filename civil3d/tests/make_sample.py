"""Crea un .pkt SINTÉTICO para pruebas (estructura aproximada de SAC; no es un archivo real de SAC)."""
import io, sys, zipfile

XAML = '''﻿<Activity mc:Ignorable="sap sap2010" x:Class="CunetaPrueba" this:CunetaPrueba.Ancho="0.6" this:CunetaPrueba.Prof="0.3"
 xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"
 xmlns:asa1="clr-namespace:Autodesk.SubassemblyComposer.ActivityLibrary;assembly=ActivityLibrary"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:sap="http://schemas.microsoft.com/netfx/2009/xaml/activities/presentation"
 xmlns:sap2010="http://schemas.microsoft.com/netfx/2010/xaml/activities/presentation"
 xmlns:this="clr-namespace:"
 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
  <x:Members>
    <x:Property Name="Ancho" Type="InArgument(x:Double)" />
    <x:Property Name="Prof" Type="InArgument(x:Double)" />
    <x:Property Name="SuperficieTN" Type="InArgument(asa1:SurfaceTarget)" />
    <x:Property Name="AreaSalida" Type="OutArgument(x:Double)" />
  </x:Members>
  <!-- comentario que debe conservarse -->
  <Flowchart DisplayName="Cuneta" sap2010:WorkflowViewState.IdRef="Flowchart_1">
    <Flowchart.StartNode>
      <FlowStep x:Name="__ReferenceID0">
        <asa1:APoint DisplayName="P1" Codes="ETW" PointGeometryType="DeltaXY" DeltaX="[Ancho]" DeltaY="[-Prof]" sap2010:WorkflowViewState.IdRef="APoint_1" />
        <FlowStep.Next>
          <FlowDecision x:Name="__ReferenceID1" Condition="[Ancho &gt; 0.5]" DisplayName="¿Ancha?">
            <FlowDecision.True>
              <FlowStep x:Name="__ReferenceID2">
                <asa1:ALink DisplayName="L1" Codes="Top,Datum" StartPoint="P1" EndPoint="AP1" />
              </FlowStep>
            </FlowDecision.True>
            <FlowDecision.False>
              <FlowStep x:Name="__ReferenceID3">
                <asa1:AShape DisplayName="S1" Codes="Cuneta" Links="L1" />
              </FlowStep>
            </FlowDecision.False>
          </FlowDecision>
        </FlowStep.Next>
      </FlowStep>
    </Flowchart.StartNode>
  </Flowchart>
</Activity>'''

META = '<Packet Guid="3f2504e0-4f89-11d3-9a0c-0305e82c3301" Name="CunetaPrueba" Descripción="ñandú" />'

def build(path, descriptor=False):
    buf = io.BytesIO()
    class NoSeek(io.RawIOBase):
        def writable(self): return True
        def write(self, b): return buf.write(b)
    target = NoSeek() if descriptor else buf
    with zipfile.ZipFile(target, "w") as z:
        z.writestr(zipfile.ZipInfo("Subassembly.xaml", (2024, 5, 1, 10, 0, 0)), XAML.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(zipfile.ZipInfo("Packet.xml", (2024, 5, 1, 10, 0, 0)), META.encode("utf-8"), compress_type=zipfile.ZIP_STORED)
        z.writestr(zipfile.ZipInfo("Preview.png", (2024, 5, 1, 10, 0, 0)), b"\x89PNG fake", compress_type=zipfile.ZIP_DEFLATED)
        z.comment = b"comentario zip"
    open(path, "wb").write(buf.getvalue())

if __name__ == "__main__":
    build(sys.argv[1], descriptor=len(sys.argv) > 2)
