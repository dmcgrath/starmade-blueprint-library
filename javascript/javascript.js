window.onload = details;

function details() {
    redraw({{ thrust_gauge }}, "thrust")
    redraw({{ shield_capacity_gauge }}, "shieldCapacity")
    redraw({{ shield_recharge_gauge }}, "shieldRecharge")
    for (var block_id in block_list) {
        block = document.getElementById("element"+block_id)
        if(block) {
            block_count = block.innerHTML;
            block.innerHTML = "<p>"+block_list[block_id]+": "+block_count+"</p>";
        }
    }
}

function redraw(thrust_gauge, system) {
  var fill = document.getElementById(system+"Fill");
  fill.setAttribute("style", "width:"+thrust_gauge+"%;background-color:"+color(thrust_gauge));
}

var great = [0, 128, 0],
    average = [255, 165, 0],
    subpar = [139, 0, 0];

function color(val) {
  val /= 100
  if (val < 0.5) {
    return colorToString(interpolate(val * 2, subpar, average));
  } else {
    return colorToString(interpolate((val-0.5) * 2, average, great));
  }
}

function interpolate(val, rgb1, rgb2) {
  var rgb = [0,0,0];
  var i;
  for (i = 0; i < 3; i++) {
    rgb[i] = Math.floor(rgb1[i] * (1.0 - val) + rgb2[i] * val);
  }
  return rgb;
}

function colorToString(rgb) {
  return "rgb(" + rgb[0] + ", " + rgb[1] + ", " + rgb[2] + ")";
}

