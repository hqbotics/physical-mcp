// Pi Zero 2 W + Camera Module v3 Enclosure
// Physical MCP v1.0 Hardware
// OpenSCAD file - export to STL for 3D printing

// Dimensions (mm)
pi_length = 65;
pi_width = 30;
pi_height = 5;  // PCB thickness

// Camera module dimensions
cam_width = 25;
cam_length = 24;
cam_height = 10;

// Wall thickness
wall = 2;

// Clearances
tolerance = 0.5;

// Total enclosure dimensions
box_l = pi_length + wall*2 + tolerance;
box_w = pi_width + wall*2 + tolerance;
box_h = pi_height + wall*2 + 8;  // Extra height for cable bend

// Module: main enclosure
module enclosure_body() {
    difference() {
        // Outer shell
        cube([box_l, box_w, box_h]);
        
        // Inner cavity for Pi
        translate([wall, wall, wall])
            cube([pi_length + tolerance, pi_width + tolerance, box_h - wall]);
        
        // Cable exit slot (camera flex cable)
        translate([box_l/2 - 6, box_w - 0.1, wall])
            cube([12, wall + tolerance + 0.1, 3]);
        
        // USB-C power port
        translate([-0.1, wall + 2, wall + 2])
            cube([wall + tolerance + 0.1, 8, 5]);
        
        // HDMI mini (optional access)
        translate([-0.1, wall + 20, wall + 2])
            cube([wall + tolerance + 0.1, 12, 5]);
        
        // Ventilation holes (top)
        for (i = [10:6:box_l-10]) {
            for (j = [wall+2:6:box_w-wall-2]) {
                translate([i, j, box_h - 0.5])
                    cylinder(h = wall + 1, d = 3, $fn=12);
            }
        }
        
        // Status LED window
        translate([box_l - wall - 0.1, box_w - wall - 8, wall + 1])
            cube([wall + 0.1, 6, 3]);
    }
}

// Module: camera holder (attached to lid or separate)
module camera_holder() {
    difference() {
        // Base mount
        cube([cam_length + wall*2, cam_width + wall*2, cam_height + wall]);
        
        // Camera cavity
        translate([wall, wall, wall])
            cube([cam_length + tolerance, cam_width + tolerance, cam_height]);
        
        // Lens hole
        translate([cam_length/2 + wall, cam_width/2 + wall, -0.1])
            cylinder(h = wall + 0.2, d = 8, $fn=32);
        
        // Mounting holes (for camera module screws)
        translate([cam_length/2 + wall - 10, cam_width/2 + wall - 6, -0.1])
            cylinder(h = wall + 0.2, d = 2, $fn=8);
        translate([cam_length/2 + wall + 10, cam_width/2 + wall - 6, -0.1])
            cylinder(h = wall + 0.2, d = 2, $fn=8);
    }
}

// Module: snap-fit lid
module lid() {
    lid_h = 2;
    difference() {
        // Flat lid
        cube([box_l, box_w, lid_h]);
        
        // Inner ridge for fit
        translate([wall - 0.3, wall - 0.3, -0.1])
            cube([pi_length + tolerance + 0.6, pi_width + tolerance + 0.6, lid_h + 0.2]);
    }
    
    // Snap-fit tabs
    translate([0, box_w/2 - 2, lid_h])
        cube([wall, 4, 2]);
    translate([box_l - wall, box_w/2 - 2, lid_h])
        cube([wall, 4, 2]);
}

// Module: mounting bracket (wall/ceiling)
module mounting_bracket() {
    bracket_thickness = 3;
    bracket_width = 30;
    bracket_height = 15;
    
    difference() {
        union() {
            // Wall plate
            cube([40, bracket_width, bracket_thickness]);
            // Angle support
            translate([0, 0, 0])
                rotate([0, 90, 0])
                linear_extrude(height = 40)
                polygon([[0,0], [bracket_height,0], [0,bracket_thickness]]);
        }
        // Screw holes
        translate([8, bracket_width/2, -0.1])
            cylinder(h = bracket_thickness + 0.2, d = 4, $fn=16);
        translate([32, bracket_width/2, -0.1])
            cylinder(h = bracket_thickness + 0.2, d = 4, $fn=16);
    }
}

// Assembly preview
module full_assembly() {
    // Main enclosure
    color("lightgray")
        enclosure_body();
    
    // Camera mount (separate piece that clips on)
    translate([box_l + 5, 0, 0])
        color("white")
        camera_holder();
    
    // Lid (exploded view)
    translate([0, 0, box_h + 5])
        color("darkgray")
        lid();
    
    // Mounting bracket
    translate([0, box_w + 10, 0])
        color("black")
        mounting_bracket();
}

// Render options
// Uncomment one:
// full_assembly();

// For STL export, uncomment individual parts:
 enclosure_body();  // Main case
// translate([box_l + 10, 0, 0]) camera_holder();  // Camera mount
// translate([0, box_w + 10, 0]) lid();  // Lid
// translate([0, box_w * 2 + 15, 0]) mounting_bracket();  // Wall mount

// Instructions:
// 1. Open in OpenSCAD (https://openscad.org/)
// 2. Uncomment the part you want to export
// 3. Render (F6) then export STL
// 4. Print at 0.2mm layer height, 20% infill, no supports needed
