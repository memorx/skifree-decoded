// Step 2: after Ghidra's auto-analysis, export every function's decompiled C,
// the function list with call counts, and every defined string with the functions that use it.
//
// Run by run.py through analyzeHeadless:
//   analyzeHeadless <project_dir> <name> -import ski32.exe -postScript ExportDecomp.java <out_dir>
//@category SkiFree

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;

public class ExportDecomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File dir = new File(args.length > 0 ? args[0] : ".");
        dir.mkdirs();

        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.setSimplificationStyle("decompile");
        if (!decompiler.openProgram(currentProgram)) {
            printerr("Could not open the decompiler: " + decompiler.getLastMessage());
            return;
        }

        FunctionManager fm = currentProgram.getFunctionManager();
        int count = 0, failures = 0;
        try (PrintWriter code = new PrintWriter(new FileWriter(new File(dir, "raw_decompiled.c")));
             PrintWriter list = new PrintWriter(new FileWriter(new File(dir, "raw_functions.tsv")))) {
            list.println("address\tname\tbytes\tcallers\tcallees\tthunk");
            for (Function f : fm.getFunctions(true)) {
                list.println(f.getEntryPoint() + "\t" + f.getName() + "\t" + f.getBody().getNumAddresses()
                    + "\t" + f.getCallingFunctions(monitor).size() + "\t" + f.getCalledFunctions(monitor).size()
                    + "\t" + (f.isThunk() ? "yes" : "no"));
                if (f.isExternal() || f.isThunk()) continue;
                DecompileResults res = decompiler.decompileFunction(f, 60, monitor);
                code.println("// ============ " + f.getName() + " @ " + f.getEntryPoint()
                    + "  (" + f.getBody().getNumAddresses() + " bytes) ============");
                if (res != null && res.decompileCompleted()) {
                    code.println(res.getDecompiledFunction().getC());
                } else {
                    code.println("// FAILED: " + (res == null ? "null" : res.getErrorMessage()));
                    failures++;
                }
                count++;
            }
        }

        // Every defined string and the functions that reference it: the anchors for naming.
        try (PrintWriter strings = new PrintWriter(new FileWriter(new File(dir, "strings_xref.tsv")))) {
            strings.println("address\tstring\tused_by");
            DataIterator it = currentProgram.getListing().getDefinedData(true);
            while (it.hasNext()) {
                Data d = it.next();
                if (!d.hasStringValue()) continue;
                StringBuilder users = new StringBuilder();
                ReferenceIterator refs = d.getReferenceIteratorTo();
                while (refs.hasNext()) {
                    Reference r = refs.next();
                    Function f = fm.getFunctionContaining(r.getFromAddress());
                    users.append(f == null ? r.getFromAddress().toString() : f.getName()).append(' ');
                }
                String s = String.valueOf(d.getValue()).replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r");
                strings.println(d.getAddress() + "\t" + s + "\t" + users.toString().trim());
            }
        }
        decompiler.dispose();
        println("ExportDecomp: " + count + " functions decompiled, " + failures + " failures -> " + dir.getAbsolutePath());
    }
}
